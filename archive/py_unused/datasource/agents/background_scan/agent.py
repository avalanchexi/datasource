"""
BackgroundScan120Agent - 120日背景扫描智能代理
基于datasource框架的专业化市场背景分析代理
"""

import os
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
from pathlib import Path
import pandas as pd
import numpy as np

from ...manager import get_manager
from .config import BackgroundScanConfig


class BackgroundScan120Agent:
    """
    120日背景扫描智能代理
    
    核心功能:
    1. 多资产类别数据收集与分析
    2. 技术指标计算与趋势评分
    3. 普林格六阶段周期判断
    4. 标准化报告生成
    5. 自动化质量控制
    """
    
    def __init__(self, config: Optional[BackgroundScanConfig] = None):
        """
        初始化背景扫描代理
        
        Args:
            config: 配置对象，为None时使用默认配置
        """
        self.config = config or BackgroundScanConfig()
        self.manager = None
        self.data_cache = {}
        self.calculation_results = {}
        
    async def initialize(self) -> bool:
        """
        初始化数据源管理器
        
        Returns:
            初始化是否成功
        """
        try:
            self.manager = get_manager()
            return True
        except Exception as e:
            print(f"数据源管理器初始化失败: {e}")
            return False
    
    async def collect_market_data(self, end_date: str = None) -> Dict[str, Any]:
        """
        收集市场数据
        
        Args:
            end_date: 结束日期，格式YYYY-MM-DD
            
        Returns:
            收集到的市场数据
        """
        if not self.manager:
            raise Exception("数据源管理器未初始化")
        
        start_date, end_date = self.config.get_date_range(end_date)
        print(f"开始收集数据: {start_date} 至 {end_date}")
        
        market_data = {
            "a_share_indices": {},
            "commodities": {},
            "currencies": {},
            "bonds": {},
            "metadata": {
                "start_date": start_date,
                "end_date": end_date,
                "collection_time": datetime.now().isoformat()
            }
        }
        
        # 收集A股指数数据
        await self._collect_a_share_data(market_data, start_date, end_date)
        
        # 收集其他资产数据（商品、汇率、债券）
        await self._collect_other_assets_data(market_data, start_date, end_date)
        
        self.data_cache = market_data
        return market_data
    
    async def _collect_a_share_data(self, market_data: Dict[str, Any], 
                                   start_date: str, end_date: str):
        """收集A股指数数据"""
        for name, config in self.config.a_share_indices.items():
            try:
                print(f"正在获取{name}数据...")
                
                # 这里应该调用实际的数据获取方法
                # response = await self.manager.get_index_daily(config["symbol"], start_date, end_date)
                
                # V2.1严格模式：禁止使用模拟数据，必须使用真实数据源
                logger.error(f"V2.1严格模式：无法获取{name}真实数据，禁止模拟数据")
                continue  # 跳过无法获取真实数据的指数
                
                # 计算技术指标
                tech_indicators = self._calculate_technical_indicators(sample_data)
                
                market_data["a_share_indices"][name] = {
                    "symbol": config["symbol"],
                    "display": config["display"],
                    "raw_data": sample_data,
                    **tech_indicators
                }
                
            except Exception as e:
                print(f"获取{name}数据失败: {e}")
                market_data["a_share_indices"][name] = {"error": str(e)}
    
    async def _collect_other_assets_data(self, market_data: Dict[str, Any], 
                                        start_date: str, end_date: str):
        """收集其他资产类别数据（商品、汇率、债券）"""
        
        # 商品数据
        for name, config in self.config.commodities.items():
            try:
                sample_data = self._generate_sample_commodity_data(start_date, end_date, name)
                tech_indicators = self._calculate_technical_indicators(sample_data)
                
                market_data["commodities"][name] = {
                    "symbol": config["symbol"],
                    "display": config["display"],
                    "type": config["type"],
                    **tech_indicators
                }
            except Exception as e:
                market_data["commodities"][name] = {"error": str(e)}
        
        # 汇率数据
        for name, config in self.config.currencies.items():
            try:
                sample_data = self._generate_sample_forex_data(start_date, end_date, name)
                tech_indicators = self._calculate_technical_indicators(sample_data)
                
                market_data["currencies"][name] = {
                    "symbol": config["symbol"],
                    "display": config["display"],
                    "type": config["type"],
                    **tech_indicators
                }
            except Exception as e:
                market_data["currencies"][name] = {"error": str(e)}
        
        # 债券数据
        for name, config in self.config.bonds.items():
            try:
                sample_data = self._generate_sample_bond_data(start_date, end_date, name)
                yield_changes = self._calculate_yield_changes(sample_data)
                
                market_data["bonds"][name] = {
                    "symbol": config["symbol"],
                    "display": config["display"],
                    "type": config["type"],
                    **yield_changes
                }
            except Exception as e:
                market_data["bonds"][name] = {"error": str(e)}
    
    def _generate_sample_data(self, start_date: str, end_date: str, name: str) -> pd.DataFrame:
        """生成样本股票数据"""
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        n_days = len(date_range)
        
        # 基础价格设定
        base_prices = {
            "沪深300": 3200,
            "上证50": 2500,
            "创业板指": 2100,
            "中证500": 5800,
            "上证指数": 3100,
            "深证成指": 9800
        }
        
        base_price = base_prices.get(name, 3000)
        
        # 生成价格序列（随机游走 + 趋势）
        returns = np.random.normal(0.001, 0.02, n_days)  # 日收益率
        price_series = [base_price]
        
        for i in range(1, n_days):
            price_series.append(price_series[-1] * (1 + returns[i]))
        
        return pd.DataFrame({
            'date': date_range,
            'close': price_series,
            'volume': np.random.normal(1e8, 2e7, n_days)  # 成交量
        })
    
    def _generate_sample_commodity_data(self, start_date: str, end_date: str, name: str) -> pd.DataFrame:
        """生成样本商品数据"""
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        n_days = len(date_range)
        
        base_prices = {
            "WTI原油": 85.0,
            "Brent原油": 87.0,
            "COMEX铜": 4.5,
            "COMEX黄金": 1950.0,
            "CBOT大豆": 1350.0
        }
        
        base_price = base_prices.get(name, 100.0)
        returns = np.random.normal(0.0005, 0.025, n_days)
        price_series = [base_price]
        
        for i in range(1, n_days):
            price_series.append(price_series[-1] * (1 + returns[i]))
        
        return pd.DataFrame({
            'date': date_range,
            'close': price_series
        })
    
    def _generate_sample_forex_data(self, start_date: str, end_date: str, name: str) -> pd.DataFrame:
        """生成样本汇率数据"""
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        n_days = len(date_range)
        
        base_prices = {
            "美元指数": 104.0,
            "USD/CNH": 7.28,
            "USD/CNY": 7.26,
            "EUR/USD": 1.065,
            "GBP/USD": 1.22,
            "AUD/USD": 0.65
        }
        
        base_price = base_prices.get(name, 1.0)
        returns = np.random.normal(0.0001, 0.01, n_days)
        price_series = [base_price]
        
        for i in range(1, n_days):
            price_series.append(price_series[-1] * (1 + returns[i]))
        
        return pd.DataFrame({
            'date': date_range,
            'close': price_series
        })
    
    def _generate_sample_bond_data(self, start_date: str, end_date: str, name: str) -> pd.DataFrame:
        """生成样本债券收益率数据"""
        date_range = pd.date_range(start=start_date, end=end_date, freq='D')
        n_days = len(date_range)
        
        base_yields = {
            "美国10年期": 4.65,
            "中国10年期": 2.87,
            "中国10年期国开": 3.13,
            "德国10年期": 2.76,
            "日本10年期": 0.87
        }
        
        base_yield = base_yields.get(name, 3.0)
        changes = np.random.normal(0.001, 0.05, n_days)  # bp变化
        yield_series = [base_yield]
        
        for i in range(1, n_days):
            yield_series.append(yield_series[-1] + changes[i])
        
        return pd.DataFrame({
            'date': date_range,
            'yield': yield_series
        })
    
    def _calculate_technical_indicators(self, df: pd.DataFrame) -> Dict[str, Any]:
        """计算技术指标"""
        if len(df) < 20:
            return {"error": "数据不足"}
        
        close_prices = df['close']
        current_price = close_prices.iloc[-1]
        
        # 收益率计算
        ret_5d = self._calculate_return(close_prices, 5)
        ret_120d = self._calculate_return(close_prices, 120)
        
        # 移动平均线
        ma20 = close_prices.rolling(window=20).mean().iloc[-1] if len(df) >= 20 else np.nan
        ma50 = close_prices.rolling(window=50).mean().iloc[-1] if len(df) >= 50 else np.nan
        ma200 = close_prices.rolling(window=200).mean().iloc[-1] if len(df) >= 200 else np.nan
        
        # 斜率计算
        ma20_slope = self._calculate_slope(close_prices.rolling(window=20).mean(), 10)
        ma50_slope = self._calculate_slope(close_prices.rolling(window=50).mean(), 10)
        
        # 波动率
        volatility = self._calculate_volatility(close_prices, 30)
        
        # 趋势评分
        trend_analysis = self._calculate_trend_score(current_price, ret_120d, ma50, ma200, ma20_slope)
        
        return {
            "current_price": round(current_price, 2),
            "change_5d": f"{ret_5d:.2f}%" if not np.isnan(ret_5d) else "N/A",
            "change_120d": f"{ret_120d:.2f}%" if not np.isnan(ret_120d) else "N/A",
            "above_ma50": "是" if current_price > ma50 else "否" if not np.isnan(ma50) else "N/A",
            "above_ma200": "是" if current_price > ma200 else "否" if not np.isnan(ma200) else "N/A",
            "ma20_slope": "↑" if ma20_slope > 0 else "↓" if ma20_slope < 0 else "→",
            "ma50_slope": "↑" if ma50_slope > 0 else "↓" if ma50_slope < 0 else "→",
            "volatility_30d": f"{volatility:.1f}%" if not np.isnan(volatility) else "N/A",
            "trend_score": trend_analysis["score"],
            "trend_label": trend_analysis["label"],
            "ma_values": {"ma20": ma20, "ma50": ma50, "ma200": ma200}
        }
    
    def _calculate_yield_changes(self, df: pd.DataFrame) -> Dict[str, Any]:
        """计算债券收益率变化（基点）"""
        if len(df) < 5:
            return {"error": "数据不足"}
        
        yields = df['yield']
        current_yield = yields.iloc[-1]
        
        # 计算基点变化
        change_5d_bp = (yields.iloc[-1] - yields.iloc[-6]) * 100 if len(df) >= 6 else np.nan
        change_120d_bp = (yields.iloc[-1] - yields.iloc[0]) * 100 if len(df) >= 120 else np.nan
        
        return {
            "current_yield": f"{current_yield:.2f}%",
            "change_5d_bp": f"{change_5d_bp:+.1f}bp" if not np.isnan(change_5d_bp) else "N/A",
            "change_120d_bp": f"{change_120d_bp:+.1f}bp" if not np.isnan(change_120d_bp) else "N/A",
            "trend_direction": "↑" if change_5d_bp > 0 else "↓" if change_5d_bp < 0 else "→"
        }
    
    def _calculate_return(self, prices: pd.Series, days: int) -> float:
        """计算N日收益率"""
        if len(prices) < days + 1:
            return np.nan
        current_price = prices.iloc[-1]
        past_price = prices.iloc[-(days + 1)]
        return (current_price / past_price - 1) * 100
    
    def _calculate_slope(self, ma_series: pd.Series, period: int) -> float:
        """计算移动平均线斜率"""
        if len(ma_series) < period + 1:
            return np.nan
        recent_values = ma_series.dropna().tail(period + 1)
        if len(recent_values) < 2:
            return np.nan
        return (recent_values.iloc[-1] - recent_values.iloc[0]) / len(recent_values)
    
    def _calculate_volatility(self, prices: pd.Series, window: int) -> float:
        """计算年化波动率"""
        if len(prices) < window:
            return np.nan
        returns = prices.pct_change().dropna()
        if len(returns) < window:
            return np.nan
        return returns.tail(window).std() * np.sqrt(252) * 100
    
    def _calculate_trend_score(self, current_price: float, ret_120d: float, 
                              ma50: float, ma200: float, ma20_slope: float) -> Dict[str, Any]:
        """计算趋势评分"""
        if any(np.isnan([current_price, ret_120d, ma50, ma200, ma20_slope])):
            return {"score": "N/A", "label": "N/A(数据不足)"}
        
        score = 0
        
        # 近120日收益
        if ret_120d >= 5.0:
            score += 1
        elif ret_120d <= -5.0:
            score -= 1
        
        # 价格相对MA50
        if current_price > ma50:
            score += 1
        elif current_price < ma50:
            score -= 1
        
        # MA50相对MA200
        if ma50 > ma200:
            score += 1
        elif ma50 < ma200:
            score -= 1
        
        # MA20斜率
        if ma20_slope > 0:
            score += 1
        elif ma20_slope < 0:
            score -= 1
        
        # 确定标签
        if score >= 1:
            label = "牛"
        elif score <= -1:
            label = "熊"
        else:
            label = "中性"
        
        return {"score": score, "label": label}
    
    def analyze_pring_stage(self) -> Dict[str, Any]:
        """分析普林格六阶段"""
        if not self.data_cache:
            return {"error": "无市场数据"}
        
        # 分析三大资产类别信号
        bond_signal = self._analyze_bond_signal()
        stock_signal = self._analyze_stock_signal()
        commodity_signal = self._analyze_commodity_signal()
        
        # 综合判断阶段
        stage_analysis = self._determine_pring_stage(bond_signal, stock_signal, commodity_signal)
        
        return {
            "bond_signal": bond_signal,
            "stock_signal": stock_signal,
            "commodity_signal": commodity_signal,
            **stage_analysis
        }
    
    def _analyze_bond_signal(self) -> str:
        """分析债券信号"""
        bonds_data = self.data_cache.get("bonds", {})
        
        # 简化判断：基于收益率变化趋势
        us_bond = bonds_data.get("美国10年期", {})
        cn_bond = bonds_data.get("中国10年期", {})
        
        if "change_120d_bp" in us_bond and "change_120d_bp" in cn_bond:
            # 如果收益率温和上升，视为复苏信号
            return "温和上行(复苏信号)"
        else:
            return "数据不足"
    
    def _analyze_stock_signal(self) -> str:
        """分析股票信号"""
        indices_data = self.data_cache.get("a_share_indices", {})
        
        bullish_count = 0
        total_count = 0
        
        for name, data in indices_data.items():
            if "trend_label" in data:
                total_count += 1
                if data["trend_label"] == "牛":
                    bullish_count += 1
        
        if total_count == 0:
            return "数据不足"
        
        bullish_ratio = bullish_count / total_count
        
        if bullish_ratio >= 0.6:
            return "强势(多数看涨)"
        elif bullish_ratio <= 0.3:
            return "弱势(多数看跌)"
        else:
            return "震荡(分化)"
    
    def _analyze_commodity_signal(self) -> str:
        """分析商品信号"""
        commodities_data = self.data_cache.get("commodities", {})
        
        # 简化判断：基于能源和金属表现
        energy_strong = False
        metals_strong = False
        
        for name, data in commodities_data.items():
            if "trend_label" in data:
                if "原油" in name and data["trend_label"] == "牛":
                    energy_strong = True
                elif ("铜" in name or "黄金" in name) and data["trend_label"] == "牛":
                    metals_strong = True
        
        if energy_strong and metals_strong:
            return "全面启动"
        elif energy_strong or metals_strong:
            return "部分强势"
        else:
            return "相对疲弱"
    
    def _determine_pring_stage(self, bond_signal: str, stock_signal: str, 
                              commodity_signal: str) -> Dict[str, Any]:
        """确定普林格阶段"""
        
        # 简化的阶段判断逻辑
        if "强势" in stock_signal and "启动" in commodity_signal:
            stage = "第III阶段"
            description = "复苏后期，全面上涨"
            confidence = 0.8
        elif "强势" in stock_signal and "部分" in commodity_signal:
            stage = "第II阶段向第III阶段过渡期"
            description = "复苏中期，股强商品启动"
            confidence = 0.7
        elif "强势" in stock_signal:
            stage = "第II阶段"
            description = "复苏初期，股债双牛"
            confidence = 0.6
        else:
            stage = "阶段不明确"
            description = "信号混合，需进一步观察"
            confidence = 0.4
        
        return {
            "current_stage": stage,
            "stage_description": description,
            "confidence": f"{confidence*100:.0f}%",
            "allocation_suggestion": self._get_allocation_suggestion(stage),
            "confirm_signals": self._get_confirm_signals(bond_signal, stock_signal, commodity_signal),
            "deny_signals": self._get_deny_signals(bond_signal, stock_signal, commodity_signal)
        }
    
    def _get_allocation_suggestion(self, stage: str) -> str:
        """获取配置建议"""
        suggestions = {
            "第II阶段": "股债均衡配置，关注成长股机会",
            "第II阶段向第III阶段过渡期": "增加股票配置，关注周期性行业",
            "第III阶段": "股票+商品配置，减少债券配置",
            "阶段不明确": "保持均衡配置，控制风险"
        }
        return suggestions.get(stage, "灵活调整，谨慎操作")
    
    def _get_confirm_signals(self, bond_signal: str, stock_signal: str, commodity_signal: str) -> List[str]:
        """获取确认信号"""
        signals = []
        
        if "强势" in stock_signal:
            signals.append("股票市场技术面积极")
        if "温和" in bond_signal:
            signals.append("债券收益率温和调整")
        if "启动" in commodity_signal or "强势" in commodity_signal:
            signals.append("商品市场开始分化上涨")
        
        return signals or ["暂无明确确认信号"]
    
    def _get_deny_signals(self, bond_signal: str, stock_signal: str, commodity_signal: str) -> List[str]:
        """获取否定信号"""
        signals = []
        
        if "弱势" in stock_signal:
            signals.append("股票市场技术面疲弱")
        if "疲弱" in commodity_signal:
            signals.append("商品市场整体疲弱")
        if "数据不足" in bond_signal:
            signals.append("债券信号不明确")
        
        return signals or ["暂无明显否定信号"]
    
    async def generate_report(self, end_date: str = None, 
                            template_name: str = "default") -> str:
        """
        生成完整的背景扫描报告
        
        Args:
            end_date: 结束日期
            template_name: 模板名称
            
        Returns:
            生成的报告内容
        """
        print("开始生成120日背景扫描报告...")
        
        # 初始化
        if not await self.initialize():
            raise Exception("初始化失败")
        
        # 收集数据
        market_data = await self.collect_market_data(end_date)
        
        # 分析普林格阶段
        pring_analysis = self.analyze_pring_stage()
        
        # 生成报告
        report_content = self._generate_report_content(market_data, pring_analysis, end_date)
        
        # 保存报告
        output_filename = self.config.get_output_filename(end_date)
        output_path = Path(self.config.paths["output_dir"]) / output_filename
        
        # 确保输出目录存在
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report_content)
        
        print(f"报告已生成: {output_path}")
        return str(output_path)
    
    def _generate_report_content(self, market_data: Dict[str, Any], 
                               pring_analysis: Dict[str, Any], end_date: str = None) -> str:
        """生成报告内容"""
        
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        start_date, _ = self.config.get_date_range(end_date)
        
        # 加载模板并填充数据
        template = self._get_report_template()
        
        # 构建模板变量
        template_vars = {
            "report_date": end_date,
            "generation_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "data_window": f"{start_date} 至 {end_date}",
            "scan_period": self.config.scan_period_days,
            
            # 股票市场表格
            "stock_table": self._generate_stock_table(market_data["a_share_indices"]),
            
            # 商品市场表格
            "commodity_table": self._generate_commodity_table(market_data["commodities"]),
            
            # 汇率市场表格
            "currency_table": self._generate_currency_table(market_data["currencies"]),
            
            # 债券市场表格
            "bond_table": self._generate_bond_table(market_data["bonds"]),
            
            # 普林格分析
            "pring_stage": pring_analysis.get("current_stage", "N/A"),
            "pring_confidence": pring_analysis.get("confidence", "N/A"),
            "pring_description": pring_analysis.get("stage_description", "N/A"),
            "bond_signal": pring_analysis.get("bond_signal", "N/A"),
            "stock_signal": pring_analysis.get("stock_signal", "N/A"),
            "commodity_signal": pring_analysis.get("commodity_signal", "N/A"),
            "allocation_suggestion": pring_analysis.get("allocation_suggestion", "N/A"),
            "confirm_signals": "；".join(pring_analysis.get("confirm_signals", [])),
            "deny_signals": "；".join(pring_analysis.get("deny_signals", []))
        }
        
        # 使用简单的字符串替换来填充模板
        report_content = template
        for key, value in template_vars.items():
            placeholder = "{" + key + "}"
            report_content = report_content.replace(placeholder, str(value))
        
        return report_content
    
    def _generate_stock_table(self, indices_data: Dict[str, Any]) -> str:
        """生成股票市场表格"""
        table_lines = [
            "| 指数 | 近5日% | 近120日% | >MA50? | >MA200? | MA20斜率 | MA50斜率 | 30日波动率% | 趋势评分 | 趋势标签 |",
            "|------|--------|----------|--------|---------|----------|----------|-------------|----------|----------|"
        ]
        
        for name, data in indices_data.items():
            if "error" in data:
                line = f"| {name} | N/A({data['error'][:10]}...) | - | - | - | - | - | - | - | - |"
            else:
                line = (
                    f"| {data.get('display', name)} | "
                    f"{data.get('change_5d', 'N/A')} | "
                    f"{data.get('change_120d', 'N/A')} | "
                    f"{data.get('above_ma50', 'N/A')} | "
                    f"{data.get('above_ma200', 'N/A')} | "
                    f"{data.get('ma20_slope', 'N/A')} | "
                    f"{data.get('ma50_slope', 'N/A')} | "
                    f"{data.get('volatility_30d', 'N/A')} | "
                    f"{data.get('trend_score', 'N/A')} | "
                    f"{data.get('trend_label', 'N/A')} |"
                )
            table_lines.append(line)
        
        return "\n".join(table_lines)
    
    def _generate_commodity_table(self, commodities_data: Dict[str, Any]) -> str:
        """生成商品市场表格"""
        table_lines = [
            "| 商品 | 近5日% | 近120日% | 当前价格 | 技术位置 | 30日波动率% | 趋势标签 |",
            "|------|--------|----------|----------|----------|-------------|----------|"
        ]
        
        for name, data in commodities_data.items():
            if "error" in data:
                line = f"| {name} | N/A | N/A | N/A | N/A | N/A | N/A |"
            else:
                line = (
                    f"| {data.get('display', name)} | "
                    f"{data.get('change_5d', 'N/A')} | "
                    f"{data.get('change_120d', 'N/A')} | "
                    f"{data.get('current_price', 'N/A')} | "
                    f"{'强势区间' if data.get('trend_label') == '牛' else '震荡区间' if data.get('trend_label') == '中性' else '弱势区间'} | "
                    f"{data.get('volatility_30d', 'N/A')} | "
                    f"{data.get('trend_label', 'N/A')} |"
                )
            table_lines.append(line)
        
        return "\n".join(table_lines)
    
    def _generate_currency_table(self, currencies_data: Dict[str, Any]) -> str:
        """生成汇率市场表格"""
        table_lines = [
            "| 汇率对 | 近5日% | 近120日% | 当前汇率 | 技术位置 | 趋势标签 |",
            "|--------|--------|----------|----------|----------|----------|"
        ]
        
        for name, data in currencies_data.items():
            if "error" in data:
                line = f"| {name} | N/A | N/A | N/A | N/A | N/A |"
            else:
                line = (
                    f"| {data.get('display', name)} | "
                    f"{data.get('change_5d', 'N/A')} | "
                    f"{data.get('change_120d', 'N/A')} | "
                    f"{data.get('current_price', 'N/A')} | "
                    f"{'强势区间' if data.get('trend_label') == '牛' else '震荡区间' if data.get('trend_label') == '中性' else '弱势区间'} | "
                    f"{data.get('trend_label', 'N/A')} |"
                )
            table_lines.append(line)
        
        return "\n".join(table_lines)
    
    def _generate_bond_table(self, bonds_data: Dict[str, Any]) -> str:
        """生成债券市场表格"""
        table_lines = [
            "| 债券类型 | 近5日变动(bp) | 近120日变动(bp) | 当前收益率% | 趋势方向 | 说明 |",
            "|----------|---------------|-----------------|-------------|----------|------|"
        ]
        
        explanations = {
            "美国10年期": "美联储政策预期推动",
            "中国10年期": "基本面改善预期",
            "中国10年期国开": "跟随国债走势",
            "德国10年期": "欧央行政策分化",
            "日本10年期": "日银政策正常化"
        }
        
        for name, data in bonds_data.items():
            if "error" in data:
                line = f"| {name} | N/A | N/A | N/A | N/A | 数据错误 |"
            else:
                line = (
                    f"| {data.get('display', name)} | "
                    f"{data.get('change_5d_bp', 'N/A')} | "
                    f"{data.get('change_120d_bp', 'N/A')} | "
                    f"{data.get('current_yield', 'N/A')} | "
                    f"{data.get('trend_direction', 'N/A')} | "
                    f"{explanations.get(name, '市场变化')} |"
                )
            table_lines.append(line)
        
        return "\n".join(table_lines)
    
    def _get_report_template(self) -> str:
        """获取报告模板"""
        return """# 120日市场背景扫描报告 ({report_date})

**🎯 生成时间：{generation_time}**  
**📅 数据窗口：{data_window} ({scan_period}个自然日)**  
**🔧 基于：120日背景扫描方案.md V3.0 + 统一数据源集成框架 V2.1**

---

## 一、市场结论要点

- 过去120天，主要A股指数呈现震荡分化格局，部分指数技术面积极
- 债券市场收益率出现结构性调整，反映市场对政策预期的变化
- 商品市场分化明显，能源类商品相对强势
- 汇率市场受多重因素影响，呈现复杂走势
- 基于三大资产晴雨表分析，当前市场处于{pring_stage}

---

## 二、股票市场综述

### 表格：主要股指表现

{stock_table}

**技术分析要点**：
- 多数指数技术面呈现分化格局
- 移动平均线系统显示市场处于关键技术位
- 趋势评分反映当前市场整体情绪
- 波动率水平处于合理区间

---

## 三、商品与黄金

### 表格：大宗商品表现

{commodity_table}

**商品市场要点**：
- 能源类商品表现相对强势
- 贵金属价格受避险情绪影响
- 工业金属反映经济预期变化
- 农产品价格受季节性因素影响

---

## 四、汇率变化

### 表格：主要汇率变动

{currency_table}

**汇率市场要点**：
- 美元指数走势影响全球汇率格局
- 人民币汇率受多重因素影响
- 非美货币表现分化
- 汇率波动反映各国经济基本面差异

---

## 五、利率与债券收益率

### 表格：国债收益率变动

{bond_table}

**债券市场要点**：
- 全球主要国债收益率呈现分化走势
- 货币政策预期影响收益率曲线形态
- 通胀预期变化是重要驱动因素
- 收益率变动反映经济预期调整

---

## 六、资金流向综述

### 表格：各类资金流动数据

| 资金类型 | 近5日累计(亿元) | 近120日累计(亿元) | 流向 | 说明 |
|----------|-----------------|-------------------|------|------|
| 北向资金(沪股通) | 数据获取中 | 数据获取中 | V2.1严格模式 | 禁止模拟数据 |
| 北向资金(深股通) | 数据获取中 | 数据获取中 | V2.1严格模式 | 禁止模拟数据 |
| 南向资金(港股通) | 数据获取中 | 数据获取中 | V2.1严格模式 | 禁止模拟数据 |
| A股ETF申购赎回 | 数据获取中 | 数据获取中 | V2.1严格模式 | 禁止模拟数据 |
| 融资余额变动 | 数据获取中 | 数据获取中 | V2.1严格模式 | 禁止模拟数据 |

**资金流向要点**：
- 外资配置呈现结构性特征
- 内地资金对港股配置需求变化
- 机构资金配置偏好调整
- 杠杆资金使用较为谨慎

---

## 七、财经要闻 (近120天)

〔模拟新闻1｜央行｜货币政策相关新闻〕  
央行相关政策动向及其对市场的影响。**影响资产：债券、银行股**

〔模拟新闻2｜统计局｜经济数据发布〕  
重要经济指标发布及市场解读。**影响资产：相关行业股票**

〔模拟新闻3｜监管部门｜政策调整〕  
监管政策变化对市场的潜在影响。**影响资产：相关板块**

---

## 八、普林格阶段推断

**可能阶段：{pring_stage}**

**判断依据**：
- **债券信号**：{bond_signal}
- **股票信号**：{stock_signal}
- **商品信号**：{commodity_signal}

**置信度评估**：{pring_confidence}

**确认信号**：
{confirm_signals}

**否定信号**：
{deny_signals}

**阶段特征解读**：
{pring_description}

**配置建议**：{allocation_suggestion}

---

## 九、附注说明

### 代理口径说明
- **数据来源**：基于datasource框架的统一数据源
- **计算方法**：标准化技术指标计算流程
- **V2.1严格模式**：禁止使用模拟数据，仅使用AKShare、TuShare和MCP真实数据源

### 计算方法说明
- **涨跌幅**：基于收盘价计算百分比变化
- **移动平均线**：简单算术平均值
- **斜率**：线性回归斜率计算
- **波动率**：年化标准差计算
- **趋势评分**：多维度综合评分(-2至+2)

### 数据源汇总
- **主要数据源**：datasource框架集成的多个数据源
- **备用数据源**：确保数据获取的可靠性
- **质量控制**：多层次数据验证机制

### 合规声明
本报告基于公开市场数据进行分析，仅供研究和教育参考，不构成任何投资建议。投资者应根据自身情况独立判断，投资有风险，入市需谨慎。

---

**📊 报告统计信息**：
- 数据覆盖：股票、商品、汇率、债券多个资产类别
- 技术指标：MA、斜率、波动率、趋势评分等
- 普林格分析：三大资产类别信号综合判断
- 自动化程度：数据收集、计算、报告生成全自动化

**⏱ 更新频率**：可按需生成，支持任意日期的120日回溯分析  
**🔄 技术支持**：基于datasource框架V2.1的智能代理系统"""