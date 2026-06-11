import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
import pandas as pd

from ..manager import DataSourceManager, get_manager
from ..calculators.technical_indicators import MarketIndicatorCalculator
from ..calculators.bond_calculator import BondCalculator, YieldCurveAnalyzer
from ..calculators.fund_flow_calculator import FundFlowCalculator
from ..calculators.pring_analyzer import PringAnalyzer


class MarketDataEngine:
    """市场数据获取和计算引擎"""
    
    def __init__(self, data_manager: Optional[DataSourceManager] = None):
        """
        初始化数据引擎
        
        Args:
            data_manager: 数据源管理器，如果为None则使用默认管理器
        """
        self.data_manager = data_manager or get_manager()
        
        # 初始化各个计算器
        self.market_calculator = MarketIndicatorCalculator(self.data_manager)
        self.bond_calculator = BondCalculator(self.data_manager)
        self.yield_analyzer = YieldCurveAnalyzer(self.data_manager)
        self.flow_calculator = FundFlowCalculator(self.data_manager)
        self.pring_analyzer = PringAnalyzer(self.data_manager)
        
        # A股指数映射
        self.a_share_indices = {
            "沪深300": "000300",
            "上证50": "000016", 
            "创业板指": "399006",
            "中证500": "000905",
            "科创50": "000688"
        }
    
    async def get_comprehensive_market_data(self, days: int = 60) -> Dict[str, Any]:
        """
        获取综合市场数据，填充报告中的N/A值
        
        Args:
            days: 数据获取天数
            
        Returns:
            综合市场数据字典
        """
        print(f"开始获取综合市场数据（{days}天）...")
        
        # 并行执行各种数据获取任务
        tasks = [
            self._get_a_share_indices_data(days),
            self._get_bond_yield_data(days),
            self._get_capital_flow_data(days),
            self._get_pring_analysis_data(days)
        ]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 整合结果
        comprehensive_data = {
            "generation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_period": f"{days}天",
            "data_sources": list(self.data_manager.list_data_sources()),
            "a_share_indices": results[0] if not isinstance(results[0], Exception) else {"error": str(results[0])},
            "bond_yields": results[1] if not isinstance(results[1], Exception) else {"error": str(results[1])},
            "capital_flows": results[2] if not isinstance(results[2], Exception) else {"error": str(results[2])},
            "pring_analysis": results[3] if not isinstance(results[3], Exception) else {"error": str(results[3])}
        }
        
        print("市场数据获取完成")
        return comprehensive_data
    
    async def _get_a_share_indices_data(self, days: int) -> Dict[str, Any]:
        """获取A股指数数据"""
        print("获取A股指数数据...")
        
        try:
            # 获取多个指数的分析
            symbols = list(self.a_share_indices.values())
            analyses = await self.market_calculator.get_multiple_indices_analysis(symbols, days)
            
            # 重新映射到中文名称
            result = {}
            for name, symbol in self.a_share_indices.items():
                if symbol in analyses:
                    analysis = analyses[symbol].copy()
                    analysis['name'] = name
                    result[name] = analysis
                else:
                    result[name] = {
                        "name": name,
                        "symbol": symbol,
                        "error": "未获取到数据"
                    }
            
            return result
            
        except Exception as e:
            return {"error": f"获取A股指数数据时发生错误: {str(e)}"}
    
    async def _get_bond_yield_data(self, days: int) -> Dict[str, Any]:
        """获取债券收益率数据"""
        print("获取债券收益率数据...")
        
        try:
            # 获取债券收益率数据
            bond_data = await self.bond_calculator.get_china_bond_yields(days)
            
            # 获取收益率曲线趋势分析
            curve_analysis = await self.yield_analyzer.analyze_yield_curve_trend(days)
            
            return {
                "bond_yields": bond_data,
                "curve_analysis": curve_analysis
            }
            
        except Exception as e:
            return {"error": f"获取债券数据时发生错误: {str(e)}"}
    
    async def _get_capital_flow_data(self, days: int) -> Dict[str, Any]:
        """获取资金流向数据"""
        print("获取资金流向数据...")
        
        try:
            # 并行获取北向和南向资金数据
            northbound_task = self.flow_calculator.get_northbound_capital_flow(days)
            southbound_task = self.flow_calculator.get_southbound_capital_flow(days)
            
            northbound_data, southbound_data = await asyncio.gather(
                northbound_task, southbound_task, return_exceptions=True
            )
            
            if isinstance(northbound_data, Exception):
                northbound_data = {"error": str(northbound_data)}
            if isinstance(southbound_data, Exception):
                southbound_data = {"error": str(southbound_data)}
            
            # 聚合资金流向分析
            if "error" not in northbound_data and "error" not in southbound_data:
                aggregated = self.flow_calculator.aggregate_capital_flow(northbound_data, southbound_data)
            else:
                aggregated = {"error": "部分资金流向数据获取失败"}
            
            return {
                "northbound": northbound_data,
                "southbound": southbound_data,
                "aggregated": aggregated
            }
            
        except Exception as e:
            return {"error": f"获取资金流向数据时发生错误: {str(e)}"}
    
    async def _get_pring_analysis_data(self, days: int) -> Dict[str, Any]:
        """获取普林格六阶段分析数据"""
        print("执行普林格六阶段分析...")
        
        try:
            analysis = await self.pring_analyzer.analyze_pring_stage(days)
            return analysis
            
        except Exception as e:
            return {"error": f"普林格分析时发生错误: {str(e)}"}
    
    def format_data_for_report(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将数据格式化为报告格式
        
        Args:
            data: 原始数据
            
        Returns:
            格式化后的数据，可直接用于报告生成
        """
        formatted = {
            "report_metadata": {
                "generation_time": data.get("generation_time", "N/A"),
                "data_period": data.get("data_period", "N/A"),
                "data_sources": ", ".join(data.get("data_sources", [])),
                "primary_source": data.get("data_sources", ["N/A"])[0] if data.get("data_sources") else "N/A"
            }
        }
        
        # 格式化A股指数数据
        if "a_share_indices" in data and "error" not in data["a_share_indices"]:
            formatted["a_share_indices"] = {}
            
            for name, analysis in data["a_share_indices"].items():
                if "error" not in analysis:
                    formatted["a_share_indices"][name] = {
                        "change_5d": f"{analysis.get('change_5d', 0):.2f}%" if analysis.get('change_5d') is not None else "N/A",
                        "change_30d": f"{analysis.get('change_30d', 0):.2f}%" if analysis.get('change_30d') is not None else "N/A",
                        "above_ma50": "是" if analysis.get('above_ma50') else "否",
                        "above_ma200": "是" if analysis.get('above_ma200') else "否",
                        "ma20_slope": f"{analysis.get('ma20_slope', 0):.4f}" if analysis.get('ma20_slope') is not None else "N/A",
                        "ma50_slope": f"{analysis.get('ma50_slope', 0):.4f}" if analysis.get('ma50_slope') is not None else "N/A",
                        "volatility_30d": f"{analysis.get('volatility_30d', 0):.2f}%" if analysis.get('volatility_30d') is not None else "N/A",
                        "trend_score": analysis.get('trend_score', 0),
                        "trend_label": analysis.get('trend_label', 'N/A')
                    }
                else:
                    formatted["a_share_indices"][name] = {
                        "change_5d": "N/A (数据获取失败)",
                        "change_30d": "N/A (数据获取失败)", 
                        "above_ma50": "N/A",
                        "above_ma200": "N/A",
                        "ma20_slope": "N/A",
                        "ma50_slope": "N/A",
                        "volatility_30d": "N/A",
                        "trend_score": 0,
                        "trend_label": "N/A (数据源需序列)"
                    }
        
        # 格式化债券收益率数据
        if "bond_yields" in data and "error" not in data["bond_yields"]:
            bond_data = data["bond_yields"]
            formatted["bond_yields"] = {}
            
            if "bond_yields" in bond_data:
                for name, bond_info in bond_data["bond_yields"].items():
                    if "error" not in bond_info:
                        formatted["bond_yields"][name] = {
                            "yield_change_5d_bp": f"{bond_info.get('yield_change_5d_bp', 0):.1f}bp" if bond_info.get('yield_change_5d_bp') is not None else "N/A",
                            "yield_change_30d_bp": f"{bond_info.get('yield_change_30d_bp', 0):.1f}bp" if bond_info.get('yield_change_30d_bp') is not None else "N/A",
                            "calculation_method": bond_info.get('calculation_method', 'N/A')
                        }
                    else:
                        formatted["bond_yields"][name] = {
                            "yield_change_5d_bp": "N/A (缺历史快照)",
                            "yield_change_30d_bp": "N/A (缺历史快照)",
                            "calculation_method": "数据获取失败"
                        }
        
        # 格式化资金流向数据
        if "capital_flows" in data and "error" not in data["capital_flows"]:
            flow_data = data["capital_flows"]
            formatted["capital_flows"] = {}
            
            if "aggregated" in flow_data and "error" not in flow_data["aggregated"]:
                agg = flow_data["aggregated"]
                formatted["capital_flows"] = {
                    "northbound_5d": f"{agg.get('northbound', {}).get('flow_5d', 0):.1f}亿元",
                    "northbound_30d": f"{agg.get('northbound', {}).get('flow_30d', 0):.1f}亿元",
                    "southbound_5d": f"{agg.get('southbound', {}).get('flow_5d', 0):.1f}亿元", 
                    "southbound_30d": f"{agg.get('southbound', {}).get('flow_30d', 0):.1f}亿元",
                    "net_flow_direction": agg.get('net_flow', {}).get('direction', 'N/A'),
                    "analysis_method": agg.get('analysis_method', 'N/A')
                }
            else:
                formatted["capital_flows"] = {
                    "northbound_5d": "N/A (披露口径变更)",
                    "northbound_30d": "N/A (披露口径变更)",
                    "southbound_5d": "N/A (披露口径变更)",
                    "southbound_30d": "N/A (披露口径变更)", 
                    "net_flow_direction": "N/A",
                    "analysis_method": "基于ETF代理估算"
                }
        
        # 格式化普林格分析数据
        if "pring_analysis" in data and "error" not in data["pring_analysis"]:
            pring = data["pring_analysis"]
            formatted["pring_analysis"] = {
                "current_stage": pring.get('stage', 'N/A'),
                "stage_description": pring.get('stage_description', 'N/A'),
                "confidence": f"{pring.get('confidence', 0)*100:.1f}%",
                "bond_signal": pring.get('asset_signals', {}).get('bonds', 'N/A'),
                "stock_signal": pring.get('asset_signals', {}).get('stocks', 'N/A'),
                "commodity_signal": pring.get('asset_signals', {}).get('commodities', 'N/A'),
                "allocation_suggestion": pring.get('allocation_suggestion', 'N/A'),
                "confirm_signals": pring.get('confirm_signals', []),
                "deny_signals": pring.get('deny_signals', [])
            }
        else:
            formatted["pring_analysis"] = {
                "current_stage": "N/A (分析失败)",
                "stage_description": "N/A",
                "confidence": "N/A",
                "bond_signal": "N/A",
                "stock_signal": "N/A", 
                "commodity_signal": "N/A",
                "allocation_suggestion": "N/A",
                "confirm_signals": [],
                "deny_signals": []
            }
        
        return formatted
    
    async def get_formatted_market_data(self, days: int = 60) -> Dict[str, Any]:
        """
        获取格式化的市场数据，可直接用于报告生成
        
        Args:
            days: 数据获取天数
            
        Returns:
            格式化的市场数据
        """
        # 获取原始数据
        raw_data = await self.get_comprehensive_market_data(days)
        
        # 格式化数据
        formatted_data = self.format_data_for_report(raw_data)
        
        return formatted_data