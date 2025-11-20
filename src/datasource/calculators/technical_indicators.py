import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple, List
from datetime import datetime, timedelta
import asyncio


class TechnicalIndicatorCalculator:
    """技术指标计算器"""
    
    def __init__(self):
        pass
    
    def calculate_ma(self, prices: pd.Series, window: int) -> pd.Series:
        """计算移动平均线"""
        return prices.rolling(window=window, min_periods=1).mean()
    
    def calculate_ma_slope(self, ma_values: pd.Series, periods: int = 5) -> float:
        """
        计算MA斜率
        
        Args:
            ma_values: MA序列
            periods: 计算斜率的周期数
            
        Returns:
            斜率值（正数表示上升趋势）
        """
        if len(ma_values) < periods:
            return 0.0
        
        recent_values = ma_values.tail(periods).values
        x = np.arange(len(recent_values))
        
        # 使用线性回归计算斜率
        slope = np.polyfit(x, recent_values, 1)[0]
        return float(slope)
    
    def calculate_volatility(self, prices: pd.Series, window: int = 30) -> float:
        """
        计算年化波动率
        
        Args:
            prices: 价格序列
            window: 计算窗口
            
        Returns:
            年化波动率（百分比）
        """
        if len(prices) < 2:
            return 0.0
        
        # 计算日收益率
        returns = prices.pct_change().dropna()
        
        if len(returns) < window:
            volatility = returns.std()
        else:
            volatility = returns.tail(window).std()
        
        # 年化（假设252个交易日）
        annualized_volatility = volatility * np.sqrt(252) * 100
        return float(annualized_volatility)
    
    def calculate_price_change(self, prices: pd.Series, periods: int) -> float:
        """
        计算价格涨跌幅
        
        Args:
            prices: 价格序列
            periods: 计算周期
            
        Returns:
            涨跌幅（百分比）
        """
        if len(prices) < periods + 1:
            return 0.0
        
        current_price = prices.iloc[-1]
        past_price = prices.iloc[-(periods + 1)]
        
        return ((current_price - past_price) / past_price) * 100
    
    def check_ma_position(self, current_price: float, ma_value: float) -> bool:
        """检查价格是否在MA之上"""
        return current_price > ma_value
    
    def calculate_trend_score(self, price_data: pd.DataFrame) -> Dict:
        """
        计算趋势评分
        
        Args:
            price_data: 包含OHLC数据的DataFrame
            
        Returns:
            趋势分析结果字典
        """
        close_prices = price_data['close']
        
        # 计算各期MA
        ma5 = self.calculate_ma(close_prices, 5)
        ma10 = self.calculate_ma(close_prices, 10)
        ma20 = self.calculate_ma(close_prices, 20)
        ma50 = self.calculate_ma(close_prices, 50)
        ma200 = self.calculate_ma(close_prices, 200)
        
        current_price = close_prices.iloc[-1]
        
        # MA位置判断
        above_ma50 = self.check_ma_position(current_price, ma50.iloc[-1]) if len(ma50) > 0 else False
        above_ma200 = self.check_ma_position(current_price, ma200.iloc[-1]) if len(ma200) > 0 else False
        
        # MA斜率
        ma20_slope = self.calculate_ma_slope(ma20, 5)
        ma50_slope = self.calculate_ma_slope(ma50, 10)
        
        # 波动率
        volatility_30d = self.calculate_volatility(close_prices, 30)
        
        # 价格变化
        change_5d = self.calculate_price_change(close_prices, 5)
        change_30d = self.calculate_price_change(close_prices, 30)
        
        # 趋势评分逻辑
        trend_score = 0
        
        # MA排列评分
        if above_ma200:
            trend_score += 30
        if above_ma50:
            trend_score += 25
        
        # MA斜率评分
        if ma50_slope > 0:
            trend_score += 20
        if ma20_slope > 0:
            trend_score += 15
        
        # 近期表现评分
        if change_5d > 0:
            trend_score += 5
        if change_30d > 0:
            trend_score += 5
        
        # 趋势标签
        if trend_score >= 80:
            trend_label = "强牛"
        elif trend_score >= 60:
            trend_label = "牛"
        elif trend_score >= 40:
            trend_label = "中性偏强"
        elif trend_score >= 20:
            trend_label = "中性"
        else:
            trend_label = "弱势"
        
        return {
            "current_price": current_price,
            "change_5d": change_5d,
            "change_30d": change_30d,
            "above_ma50": above_ma50,
            "above_ma200": above_ma200,
            "ma20_slope": ma20_slope,
            "ma50_slope": ma50_slope,
            "volatility_30d": volatility_30d,
            "trend_score": trend_score,
            "trend_label": trend_label,
            "ma_values": {
                "ma5": ma5.iloc[-1] if len(ma5) > 0 else None,
                "ma10": ma10.iloc[-1] if len(ma10) > 0 else None,
                "ma20": ma20.iloc[-1] if len(ma20) > 0 else None,
                "ma50": ma50.iloc[-1] if len(ma50) > 0 else None,
                "ma200": ma200.iloc[-1] if len(ma200) > 0 else None,
            }
        }


class TechnicalIndicators(TechnicalIndicatorCalculator):
    """兼容旧版接口的技术指标封装"""

    def calculate_rsi(self, prices: pd.Series, window: int = 14) -> pd.Series:
        """计算相对强弱指标RSI"""
        if prices is None or len(prices) == 0:
            return pd.Series(dtype=float)

        delta = prices.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.ewm(alpha=1 / window, min_periods=window).mean()
        avg_loss = loss.ewm(alpha=1 / window, min_periods=window).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        rsi = rsi.fillna(50.0).clip(lower=0, upper=100)
        rsi.name = 'rsi'
        return rsi


class MarketIndicatorCalculator:
    """市场指标计算器"""
    
    def __init__(self, data_manager):
        self.data_manager = data_manager
        self.tech_calculator = TechnicalIndicatorCalculator()
    
    async def get_index_analysis(self, symbol: str, start_date: str, end_date: str) -> Dict:
        """
        获取指数技术分析
        
        Args:
            symbol: 指数代码
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            分析结果字典
        """
        try:
            # 获取指数数据
            response = await self.data_manager.get_index_daily(symbol, start_date, end_date)
            
            if response.error or response.data is None or response.data.empty:
                return {
                    "error": f"无法获取 {symbol} 的数据: {response.error}",
                    "symbol": symbol
                }
            
            # 数据预处理
            df = response.data.copy()
            
            # 尝试标准化列名
            column_mapping = {
                '收盘': 'close',
                '开盘': 'open', 
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                'close': 'close',
                'open': 'open',
                'high': 'high', 
                'low': 'low',
                'volume': 'volume'
            }
            
            # 重命名列
            for old_col, new_col in column_mapping.items():
                if old_col in df.columns:
                    df = df.rename(columns={old_col: new_col})
            
            # 确保有必要的列
            if 'close' not in df.columns:
                # 尝试找到价格列
                price_cols = [col for col in df.columns if any(keyword in col.lower() for keyword in ['price', 'close', '收盘', '价格'])]
                if price_cols:
                    df['close'] = df[price_cols[0]]
                else:
                    return {
                        "error": f"无法找到 {symbol} 的价格数据列",
                        "symbol": symbol
                    }
            
            # 确保数据按日期排序
            if 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
            elif df.index.name == 'date' or 'date' in str(df.index.dtype):
                df = df.sort_index()
            
            # 计算技术指标
            analysis = self.tech_calculator.calculate_trend_score(df)
            analysis['symbol'] = symbol
            analysis['data_source'] = response.source
            analysis['last_update'] = response.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            
            return analysis
            
        except Exception as e:
            return {
                "error": f"分析 {symbol} 时发生错误: {str(e)}",
                "symbol": symbol
            }
    
    async def get_multiple_indices_analysis(self, symbols: List[str], days: int = 60) -> Dict[str, Dict]:
        """
        批量获取多个指数的分析
        
        Args:
            symbols: 指数代码列表
            days: 数据天数
            
        Returns:
            指数分析结果字典
        """
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        
        results = {}
        
        # 并行获取数据
        tasks = []
        for symbol in symbols:
            task = self.get_index_analysis(symbol, start_date, end_date)
            tasks.append(task)
        
        analyses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, analysis in enumerate(analyses):
            symbol = symbols[i]
            if isinstance(analysis, Exception):
                results[symbol] = {
                    "error": f"获取 {symbol} 数据时发生异常: {str(analysis)}",
                    "symbol": symbol
                }
            else:
                results[symbol] = analysis
        
        return results
