import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Tuple
from datetime import datetime, timedelta
import asyncio
import re

from ..utils.yahoo_finance import fetch_price_history


class FundFlowCalculator:
    """资金流向计算器"""
    
    def __init__(self, data_manager):
        self.data_manager = data_manager
    
    async def get_northbound_capital_flow(self, days: int = 30) -> Dict:
        """
        获取北向资金流向数据
        
        Args:
            days: 获取天数
            
        Returns:
            北向资金流向分析
        """
        try:
            # 北向资金代理指标：港股通ETF和沪深300相关ETF的资金流向
            proxy_etfs = {
                "沪深300ETF": "510300",   # 华泰柏瑞沪深300ETF
                "恒生ETF": "159920",      # 华夏恒生ETF
                "港股ETF": "513900"       # 华夏港股通精选股票ETF
            }
            
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            results = {}
            
            for name, symbol in proxy_etfs.items():
                try:
                    response = await self.data_manager.get_stock_daily(symbol, start_date, end_date)

                    data_source = getattr(response, "source", "manager") if response else "manager"
                    df = None

                    if response and not response.error and response.data is not None and not response.data.empty:
                        df = response.data.copy()
                    else:
                        df = fetch_price_history(symbol, start_date, end_date, buffer_days=30)
                        if df is None or df.empty:
                            results[name] = {
                                "error": f"无法获取{name}数据",
                                "symbol": symbol
                            }
                            continue
                        data_source = "YahooFinance"
                    
                    # 标准化列名
                    column_mapping = {
                        '收盘': 'close',
                        '成交量': 'volume',
                        '成交额': 'amount',
                        'close': 'close',
                        'volume': 'volume'
                    }
                    
                    for old_col, new_col in column_mapping.items():
                        if old_col in df.columns:
                            df = df.rename(columns={old_col: new_col})

                    # 确保有价格和成交量数据
                    if 'close' not in df.columns:
                        price_cols = [col for col in df.columns if any(keyword in col.lower() 
                                     for keyword in ['price', 'close', '收盘', '价格'])]
                        if price_cols:
                            df['close'] = df[price_cols[0]]
                        else:
                            continue
                    
                    if 'volume' not in df.columns:
                        vol_cols = [col for col in df.columns if any(keyword in col.lower() 
                                   for keyword in ['volume', '成交量', '量'])]
                        if vol_cols:
                            df['volume'] = df[vol_cols[0]]
                        else:
                            df['volume'] = 0
                    
                    # 计算资金流向指标
                    if 'date' in df.columns:
                        df['date'] = pd.to_datetime(df['date'], errors='coerce')
                        df = df.dropna(subset=['date']).sort_values('date')
                    else:
                        df = df.sort_index() if hasattr(df.index, 'sort_values') else df.sort_values(df.columns[0])
                    
                    prices = df['close'].astype(float)
                    volumes = df['volume'].astype(float)
                    
                    # 计算价格变化率
                    price_changes = prices.pct_change().fillna(0)
                    
                    # 估算资金流向（价格上涨且放量为流入）
                    money_flow = []
                    for i in range(len(prices)):
                        if i == 0:
                            money_flow.append(0)
                            continue
                        
                        price_change = price_changes.iloc[i]
                        volume = volumes.iloc[i]
                        avg_price = (prices.iloc[i] + prices.iloc[i-1]) / 2
                        
                        # 简化的资金流向计算：价格上涨时为正流入，下跌时为负流出
                        flow = price_change * volume * avg_price / 1e8  # 转换为亿元
                        money_flow.append(flow)
                    
                    df['money_flow'] = money_flow
                    
                    # 计算累计流向
                    recent_5d_flow = df['money_flow'].tail(5).sum() if len(df) >= 5 else 0
                    recent_30d_flow = df['money_flow'].tail(30).sum() if len(df) >= 30 else 0
                    recent_120d_flow = df['money_flow'].tail(120).sum() if len(df) >= 120 else df['money_flow'].sum()

                    results[name] = {
                        "symbol": symbol,
                        "flow_5d": round(recent_5d_flow, 2),
                        "flow_30d": round(recent_30d_flow, 2),
                        "flow_120d": round(recent_120d_flow, 2),
                        "current_price": prices.iloc[-1],
                        "price_change_5d": round(((prices.iloc[-1] - prices.iloc[-6]) / prices.iloc[-6] * 100) if len(prices) >= 6 else 0, 2),
                        "avg_daily_volume": round(volumes.tail(10).mean() / 1e4, 2),  # 万手
                        "data_source": data_source,
                        "calculation_method": "基于ETF价量关系估算",
                        "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                except Exception as e:
                    results[name] = {
                        "error": f"计算{name}资金流向时发生错误: {str(e)}",
                        "symbol": symbol
                    }
            
            return results
            
        except Exception as e:
            return {
                "error": f"获取北向资金数据时发生错误: {str(e)}"
            }
    
    async def get_southbound_capital_flow(self, days: int = 30) -> Dict:
        """
        获取南向资金流向数据（港股通）
        
        Args:
            days: 获取天数
            
        Returns:
            南向资金流向分析
        """
        try:
            # 南向资金代理指标：港股相关ETF
            hk_etfs = {
                "恒生指数ETF": "159920",
                "恒生科技ETF": "513130", 
                "港股通50ETF": "513550"
            }
            
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            results = {}
            
            for name, symbol in hk_etfs.items():
                try:
                    response = await self.data_manager.get_stock_daily(symbol, start_date, end_date)
                    
                    if response.error or response.data is None or response.data.empty:
                        results[name] = {
                            "error": f"无法获取{name}数据",
                            "symbol": symbol
                        }
                        continue
                    
                    df = response.data.copy()
                    
                    # 处理数据（类似北向资金的逻辑）
                    column_mapping = {
                        '收盘': 'close',
                        '成交量': 'volume',
                        'close': 'close',
                        'volume': 'volume'
                    }
                    
                    for old_col, new_col in column_mapping.items():
                        if old_col in df.columns:
                            df = df.rename(columns={old_col: new_col})
                    
                    if 'close' not in df.columns:
                        continue
                    
                    if 'volume' not in df.columns:
                        vol_cols = [col for col in df.columns if any(keyword in col.lower() 
                                   for keyword in ['volume', '成交量', '量'])]
                        if vol_cols:
                            df['volume'] = df[vol_cols[0]]
                        else:
                            df['volume'] = 0
                    
                    prices = df['close'].astype(float)
                    volumes = df['volume'].astype(float)
                    
                    # 计算资金流向
                    price_changes = prices.pct_change().fillna(0)
                    
                    money_flow = []
                    for i in range(len(prices)):
                        if i == 0:
                            money_flow.append(0)
                            continue
                        
                        price_change = price_changes.iloc[i]
                        volume = volumes.iloc[i]
                        avg_price = (prices.iloc[i] + prices.iloc[i-1]) / 2
                        
                        flow = price_change * volume * avg_price / 1e8
                        money_flow.append(flow)
                    
                    df['money_flow'] = money_flow
                    
                    # 计算累计流向
                    recent_5d_flow = df['money_flow'].tail(5).sum() if len(df) >= 5 else 0
                    recent_30d_flow = df['money_flow'].tail(30).sum() if len(df) >= 30 else 0
                    recent_120d_flow = df['money_flow'].tail(120).sum() if len(df) >= 120 else df['money_flow'].sum()

                    results[name] = {
                        "symbol": symbol,
                        "flow_5d": round(recent_5d_flow, 2),
                        "flow_30d": round(recent_30d_flow, 2),
                        "flow_120d": round(recent_120d_flow, 2),
                        "current_price": prices.iloc[-1],
                        "price_change_5d": round(((prices.iloc[-1] - prices.iloc[-6]) / prices.iloc[-6] * 100) if len(prices) >= 6 else 0, 2),
                        "data_source": response.source,
                        "calculation_method": "基于港股ETF价量关系估算",
                        "last_update": response.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                    }
                    
                except Exception as e:
                    results[name] = {
                        "error": f"计算{name}资金流向时发生错误: {str(e)}",
                        "symbol": symbol
                    }
            
            return results
            
        except Exception as e:
            return {
                "error": f"获取南向资金数据时发生错误: {str(e)}"
            }
    
    def aggregate_capital_flow(self, northbound_data: Dict, southbound_data: Dict) -> Dict:
        """
        聚合资金流向数据
        
        Args:
            northbound_data: 北向资金数据
            southbound_data: 南向资金数据
            
        Returns:
            聚合的资金流向分析
        """
        try:
            # 计算北向资金净流入
            north_flow_5d = 0
            north_flow_30d = 0
            north_flow_120d = 0
            north_count = 0

            for name, data in northbound_data.items():
                if "error" not in data and "flow_5d" in data:
                    north_flow_5d += data.get("flow_5d", 0)
                    north_flow_30d += data.get("flow_30d", 0)
                    north_flow_120d += data.get("flow_120d", data.get("flow_30d", 0))
                    north_count += 1

            # 计算南向资金净流入  
            south_flow_5d = 0
            south_flow_30d = 0
            south_flow_120d = 0
            south_count = 0

            for name, data in southbound_data.items():
                if "error" not in data and "flow_5d" in data:
                    south_flow_5d += data.get("flow_5d", 0)
                    south_flow_30d += data.get("flow_30d", 0)
                    south_flow_120d += data.get("flow_120d", data.get("flow_30d", 0))
                    south_count += 1
            
            # 综合分析
            return {
                "northbound": {
                    "flow_5d": round(north_flow_5d, 2),
                    "flow_30d": round(north_flow_30d, 2),
                    "flow_120d": round(north_flow_120d, 2),
                    "etf_count": north_count,
                    "trend": "流入" if north_flow_5d > 0 else "流出" if north_flow_5d < 0 else "平衡"
                },
                "southbound": {
                    "flow_5d": round(south_flow_5d, 2),
                    "flow_30d": round(south_flow_30d, 2),
                    "flow_120d": round(south_flow_120d, 2),
                    "etf_count": south_count,
                    "trend": "流入" if south_flow_5d > 0 else "流出" if south_flow_5d < 0 else "平衡"
                },
                "net_flow": {
                    "flow_5d": round(north_flow_5d - south_flow_5d, 2),
                    "flow_30d": round(north_flow_30d - south_flow_30d, 2),
                    "flow_120d": round(north_flow_120d - south_flow_120d, 2),
                    "direction": "北向净流入" if (north_flow_5d - south_flow_5d) > 0 else "南向净流入" if (north_flow_5d - south_flow_5d) < 0 else "基本平衡"
                },
                "analysis_method": "基于相关ETF价量关系的估算方法",
                "data_limitation": "实际资金流向数据需要官方披露，此为技术估算",
                "last_update": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except Exception as e:
            return {
                "error": f"聚合资金流向数据时发生错误: {str(e)}"
            }
