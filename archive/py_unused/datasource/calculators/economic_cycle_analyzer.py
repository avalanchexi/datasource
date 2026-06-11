"""
经济周期分析器 - Economic Cycle Analyzer
集成Pring六阶段分析和宏观经济指标的经济周期判断系统

实现功能:
1. 经济周期阶段识别 (复苏、扩张、过热、滞胀、衰退、萧条)
2. 库存周期分析 (主动/被动 补库存/去库存)
3. 宏观指标追踪 (PPI、CPI、PMI、BDI)
4. V2.1 Pring分析集成
5. 周期转换预测
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
import logging

from ..manager import DataSourceManager, get_manager
from ..models.base import DataResponse
from .pring_analyzer import PringAnalyzer, PringResult
from .technical_indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

@dataclass
class MacroIndicators:
    """宏观经济指标数据"""
    ppi_value: float
    ppi_trend: str  # "上升", "下降", "稳定"
    ppi_momentum: float
    
    cpi_value: float  
    cpi_trend: str
    cpi_momentum: float
    
    pmi_value: float
    pmi_trend: str  # ">52", ">50", "<50", "<48"
    pmi_momentum: float
    
    bdi_value: Optional[float] = None
    bdi_trend: Optional[str] = None
    
    data_date: datetime = None

@dataclass
class CycleStageResult:
    """经济周期阶段分析结果"""
    stage: str  # 周期阶段
    confidence: float  # 置信度 0-100
    stage_score: float  # 阶段评分 0-100
    duration_estimate: int  # 预计持续天数
    transition_probability: float  # 转换概率 0-1
    next_stage: str  # 下一阶段预测
    
    # 支撑数据
    macro_indicators: MacroIndicators
    pring_result: Optional[PringResult] = None
    inventory_phase: str = "未知"
    
    # 风险提示
    risk_factors: List[str] = None
    support_factors: List[str] = None

class EconomicCycleAnalyzer:
    """经济周期分析器"""
    
    def __init__(self, manager: Optional[DataSourceManager] = None):
        self.manager = manager or get_manager()
        self.pring_analyzer = PringAnalyzer()
        self.tech_indicators = TechnicalIndicators()
        
        # 经济周期阶段定义矩阵
        self.cycle_definitions = {
            "复苏": {
                "ppi": {"trend": "上升", "threshold": 0.5},
                "cpi": {"trend": "稳定", "range": (1.5, 3.0)},
                "pmi": {"threshold": 50.0, "momentum": "positive"},
                "inventory": "主动补库存",
                "description": "经济开始回暖，需求逐步恢复",
                "typical_duration": (90, 180),
                "bull_probability": 0.75
            },
            "扩张": {
                "ppi": {"trend": "高位", "threshold": 2.0},
                "cpi": {"trend": "上升", "range": (2.0, 4.0)},
                "pmi": {"threshold": 52.0, "momentum": "strong"},
                "inventory": "被动补库存", 
                "description": "经济高速增长，通胀压力显现",
                "typical_duration": (120, 240),
                "bull_probability": 0.85
            },
            "过热": {
                "ppi": {"trend": "下降", "from_high": True},
                "cpi": {"trend": "高位", "threshold": 3.5},
                "pmi": {"threshold": 50.0, "declining": True},
                "inventory": "主动去库存",
                "description": "经济过度扩张，开始出现调整压力",
                "typical_duration": (60, 120),
                "bull_probability": 0.35
            },
            "滞胀": {
                "ppi": {"trend": "下降", "momentum": "negative"},
                "cpi": {"trend": "高位", "persistent": True},
                "pmi": {"threshold": 48.0, "below": True},
                "inventory": "主动去库存",
                "description": "经济增长放缓但通胀居高不下",
                "typical_duration": (90, 180),
                "bull_probability": 0.20
            },
            "衰退": {
                "ppi": {"trend": "低位", "negative": True},
                "cpi": {"trend": "下降", "momentum": "negative"},
                "pmi": {"threshold": 45.0, "below": True},
                "inventory": "被动去库存",
                "description": "经济明显下滑，通缩风险上升",
                "typical_duration": (120, 300),
                "bull_probability": 0.15
            },
            "萧条": {
                "ppi": {"trend": "低位", "deep_negative": True},
                "cpi": {"trend": "低位", "deflation_risk": True},
                "pmi": {"threshold": 40.0, "below": True},
                "inventory": "被动去库存",
                "description": "经济深度衰退，通缩压力严重",
                "typical_duration": (180, 360),
                "bull_probability": 0.10
            }
        }
        
        # 库存周期判断矩阵
        self.inventory_phases = {
            "主动补库存": {"ppi": "上升", "demand": "strong", "expectation": "optimistic"},
            "被动补库存": {"ppi": "高位稳定", "demand": "weakening", "expectation": "cautious"},
            "主动去库存": {"ppi": "下降", "demand": "weak", "expectation": "pessimistic"},
            "被动去库存": {"ppi": "低位", "demand": "recovering", "expectation": "tentative"}
        }

    async def analyze_economic_cycle(self, 
                                   benchmark_symbol: str = "000001", 
                                   analysis_date: Optional[str] = None) -> CycleStageResult:
        """
        执行完整的经济周期分析
        
        Args:
            benchmark_symbol: 基准指数代码
            analysis_date: 分析日期，默认为今日
            
        Returns:
            CycleStageResult: 经济周期分析结果
        """
        if not analysis_date:
            analysis_date = datetime.now().strftime('%Y-%m-%d')
            
        logger.info(f"Starting economic cycle analysis for {analysis_date}")
        
        try:
            # 并行获取数据
            tasks = [
                self._get_macro_indicators(analysis_date),
                self._get_pring_analysis(benchmark_symbol, analysis_date)
            ]
            
            macro_indicators, pring_result = await asyncio.gather(*tasks)
            
            # 经济周期阶段识别
            cycle_stage, confidence = self._identify_cycle_stage(macro_indicators)
            
            # 库存周期判断
            inventory_phase = self._determine_inventory_phase(macro_indicators)
            
            # 阶段评分计算
            stage_score = self._calculate_stage_score(cycle_stage, macro_indicators, pring_result)
            
            # 持续时间估算
            duration_estimate = self._estimate_stage_duration(cycle_stage, macro_indicators)
            
            # 转换概率计算
            transition_prob, next_stage = self._calculate_transition_probability(
                cycle_stage, duration_estimate, macro_indicators
            )
            
            # 风险因子分析
            risk_factors, support_factors = self._analyze_cycle_factors(
                cycle_stage, macro_indicators, pring_result
            )
            
            result = CycleStageResult(
                stage=cycle_stage,
                confidence=confidence,
                stage_score=stage_score,
                duration_estimate=duration_estimate,
                transition_probability=transition_prob,
                next_stage=next_stage,
                macro_indicators=macro_indicators,
                pring_result=pring_result,
                inventory_phase=inventory_phase,
                risk_factors=risk_factors or [],
                support_factors=support_factors or []
            )
            
            logger.info(f"Cycle analysis completed: {cycle_stage} (confidence: {confidence:.1f}%)")
            return result
            
        except Exception as e:
            logger.error(f"Economic cycle analysis failed: {e}")
            raise

    async def _get_macro_indicators(self, analysis_date: str) -> MacroIndicators:
        """获取宏观经济指标数据"""
        try:
            # 获取PPI数据
            ppi_data = await self._fetch_ppi_data(analysis_date)
            ppi_value, ppi_trend, ppi_momentum = self._analyze_ppi_data(ppi_data)
            
            # 获取CPI数据
            cpi_data = await self._fetch_cpi_data(analysis_date)
            cpi_value, cpi_trend, cpi_momentum = self._analyze_cpi_data(cpi_data)
            
            # 获取PMI数据
            pmi_data = await self._fetch_pmi_data(analysis_date)
            pmi_value, pmi_trend, pmi_momentum = self._analyze_pmi_data(pmi_data)
            
            # 获取BDI数据（可选）
            bdi_value, bdi_trend = None, None
            try:
                bdi_data = await self._fetch_bdi_data(analysis_date)
                bdi_value, bdi_trend = self._analyze_bdi_data(bdi_data)
            except Exception as e:
                logger.warning(f"BDI data not available: {e}")
            
            return MacroIndicators(
                ppi_value=ppi_value,
                ppi_trend=ppi_trend,
                ppi_momentum=ppi_momentum,
                cpi_value=cpi_value,
                cpi_trend=cpi_trend,
                cpi_momentum=cpi_momentum,
                pmi_value=pmi_value,
                pmi_trend=pmi_trend,
                pmi_momentum=pmi_momentum,
                bdi_value=bdi_value,
                bdi_trend=bdi_trend,
                data_date=datetime.strptime(analysis_date, '%Y-%m-%d')
            )
            
        except Exception as e:
            logger.warning(f"Failed to get macro indicators: {e}")
            # 返回默认值
            return MacroIndicators(
                ppi_value=2.0, ppi_trend="稳定", ppi_momentum=0.0,
                cpi_value=2.5, cpi_trend="稳定", cpi_momentum=0.0,
                pmi_value=50.5, pmi_trend=">50", pmi_momentum=0.0,
                data_date=datetime.strptime(analysis_date, '%Y-%m-%d')
            )

    async def _get_pring_analysis(self, symbol: str, analysis_date: str) -> Optional[PringResult]:
        """获取Pring分析结果"""
        try:
            end_date = analysis_date
            start_date = (datetime.strptime(analysis_date, '%Y-%m-%d') - timedelta(days=365)).strftime('%Y-%m-%d')
            
            response = await self.manager.get_stock_daily(symbol, start_date, end_date)
            if response.error:
                logger.warning(f"Failed to get stock data for Pring analysis: {response.error}")
                return None
                
            pring_result = await self.pring_analyzer.analyze_with_inventory_cycle(
                response.data, symbol
            )
            
            return pring_result
            
        except Exception as e:
            logger.warning(f"Pring analysis failed: {e}")
            return None

    def _identify_cycle_stage(self, indicators: MacroIndicators) -> Tuple[str, float]:
        """识别经济周期阶段"""
        stage_scores = {}
        
        for stage, definition in self.cycle_definitions.items():
            score = 0
            max_score = 0
            
            # PPI评估
            ppi_def = definition["ppi"]
            max_score += 25
            if self._match_ppi_condition(indicators.ppi_value, indicators.ppi_trend, 
                                       indicators.ppi_momentum, ppi_def):
                score += 25
                
            # CPI评估  
            cpi_def = definition["cpi"]
            max_score += 25
            if self._match_cpi_condition(indicators.cpi_value, indicators.cpi_trend,
                                       indicators.cpi_momentum, cpi_def):
                score += 25
                
            # PMI评估
            pmi_def = definition["pmi"]
            max_score += 25
            if self._match_pmi_condition(indicators.pmi_value, indicators.pmi_trend,
                                       indicators.pmi_momentum, pmi_def):
                score += 25
                
            # 库存周期一致性
            expected_inventory = definition["inventory"]
            actual_inventory = self._determine_inventory_phase(indicators)
            max_score += 25
            if expected_inventory == actual_inventory:
                score += 25
            elif self._is_compatible_inventory_phase(expected_inventory, actual_inventory):
                score += 15
                
            stage_scores[stage] = (score / max_score) * 100
            
        # 选择得分最高的阶段
        best_stage = max(stage_scores, key=stage_scores.get)
        confidence = stage_scores[best_stage]
        
        # 如果置信度太低，标记为过渡期
        if confidence < 60:
            return "过渡期", confidence
            
        return best_stage, confidence

    def _determine_inventory_phase(self, indicators: MacroIndicators) -> str:
        """确定库存周期阶段"""
        ppi_trend = indicators.ppi_trend
        ppi_momentum = indicators.ppi_momentum
        pmi_value = indicators.pmi_value
        
        # 基于PPI和PMI的组合判断
        if ppi_trend == "上升" and pmi_value > 50:
            return "主动补库存"
        elif ppi_trend in ["高位", "稳定"] and pmi_value > 50:
            if ppi_momentum < 0:  # PPI开始回落
                return "被动补库存"
            else:
                return "主动补库存"
        elif ppi_trend == "下降" and pmi_value < 50:
            return "主动去库存"
        else:
            return "被动去库存"

    def _calculate_stage_score(self, stage: str, indicators: MacroIndicators, 
                             pring_result: Optional[PringResult]) -> float:
        """计算阶段评分"""
        base_score = self.cycle_definitions.get(stage, {}).get("bull_probability", 0.5) * 100
        
        # Pring分析调整
        if pring_result:
            pring_adjustment = (pring_result.final_score - 50) * 0.3
            base_score = base_score + pring_adjustment
            
        # 宏观指标强度调整
        macro_strength = self._assess_macro_strength(indicators)
        base_score = base_score * (0.7 + macro_strength * 0.3)
        
        return max(0, min(100, base_score))

    def _estimate_stage_duration(self, stage: str, indicators: MacroIndicators) -> int:
        """估算阶段持续时间"""
        typical_duration = self.cycle_definitions.get(stage, {}).get("typical_duration", (90, 180))
        
        # 基于指标动量调整
        momentum_factor = (abs(indicators.ppi_momentum) + abs(indicators.cpi_momentum) + 
                          abs(indicators.pmi_momentum)) / 3
        
        if momentum_factor > 0.5:  # 高动量，转换更快
            return typical_duration[0]
        else:
            return int((typical_duration[0] + typical_duration[1]) / 2)

    def _calculate_transition_probability(self, current_stage: str, duration: int, 
                                        indicators: MacroIndicators) -> Tuple[float, str]:
        """计算阶段转换概率"""
        # 周期转换序列
        stage_sequence = ["萧条", "复苏", "扩张", "过热", "滞胀", "衰退"]
        
        try:
            current_index = stage_sequence.index(current_stage)
            next_stage = stage_sequence[(current_index + 1) % len(stage_sequence)]
        except ValueError:
            next_stage = "复苏"  # 默认
            
        # 基于持续时间的转换概率
        typical_range = self.cycle_definitions.get(current_stage, {}).get("typical_duration", (90, 180))
        
        if duration < typical_range[0]:
            transition_prob = 0.2
        elif duration > typical_range[1]:
            transition_prob = 0.8
        else:
            # 线性插值
            progress = (duration - typical_range[0]) / (typical_range[1] - typical_range[0])
            transition_prob = 0.2 + progress * 0.6
            
        # 指标动量调整
        total_momentum = abs(indicators.ppi_momentum) + abs(indicators.cpi_momentum) + abs(indicators.pmi_momentum)
        momentum_adjustment = min(0.3, total_momentum / 10)
        transition_prob += momentum_adjustment
        
        return min(0.9, transition_prob), next_stage

    def _analyze_cycle_factors(self, stage: str, indicators: MacroIndicators, 
                             pring_result: Optional[PringResult]) -> Tuple[List[str], List[str]]:
        """分析周期风险和支撑因素"""
        risk_factors = []
        support_factors = []
        
        # 基于当前阶段的风险因子
        if stage in ["过热", "滞胀"]:
            risk_factors.append("通胀压力上升")
            if indicators.cpi_value > 3.5:
                risk_factors.append("CPI超过警戒线")
                
        if stage in ["衰退", "萧条"]:
            risk_factors.append("经济下行压力")
            if indicators.pmi_value < 45:
                risk_factors.append("PMI深度收缩")
                
        # 支撑因素
        if stage in ["复苏", "扩张"]:
            support_factors.append("经济增长动能")
            if indicators.pmi_value > 52:
                support_factors.append("PMI强劲扩张")
                
        # Pring分析的贡献
        if pring_result:
            if pring_result.final_score > 70:
                support_factors.append("技术面强势")
            elif pring_result.final_score < 30:
                risk_factors.append("技术面疲弱")
                
        return risk_factors, support_factors

    # 宏观数据获取方法（模拟实现）
    async def _fetch_ppi_data(self, date: str) -> List[Dict]:
        """获取PPI数据"""
        # 模拟PPI数据
        return [
            {"date": date, "value": 2.3},
            {"date": (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d'), "value": 2.1},
            {"date": (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=60)).strftime('%Y-%m-%d'), "value": 1.9}
        ]

    async def _fetch_cpi_data(self, date: str) -> List[Dict]:
        """获取CPI数据"""
        return [
            {"date": date, "value": 2.8},
            {"date": (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d'), "value": 2.6},
            {"date": (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=60)).strftime('%Y-%m-%d'), "value": 2.4}
        ]

    async def _fetch_pmi_data(self, date: str) -> List[Dict]:
        """获取PMI数据"""
        return [
            {"date": date, "value": 51.2},
            {"date": (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d'), "value": 50.8},
            {"date": (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=60)).strftime('%Y-%m-%d'), "value": 50.5}
        ]

    async def _fetch_bdi_data(self, date: str) -> List[Dict]:
        """获取BDI数据"""
        return [
            {"date": date, "value": 1250},
            {"date": (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=7)).strftime('%Y-%m-%d'), "value": 1230}
        ]

    # 数据分析方法
    def _analyze_ppi_data(self, data: List[Dict]) -> Tuple[float, str, float]:
        """分析PPI数据"""
        if not data or len(data) < 2:
            return 2.0, "稳定", 0.0
            
        current = data[0]["value"]
        previous = data[1]["value"]
        momentum = current - previous
        
        if momentum > 0.3:
            trend = "上升"
        elif momentum < -0.3:
            trend = "下降" 
        elif current > 3.0:
            trend = "高位"
        elif current < 0.5:
            trend = "低位"
        else:
            trend = "稳定"
            
        return current, trend, momentum

    def _analyze_cpi_data(self, data: List[Dict]) -> Tuple[float, str, float]:
        """分析CPI数据"""
        if not data or len(data) < 2:
            return 2.5, "稳定", 0.0
            
        current = data[0]["value"]
        previous = data[1]["value"]
        momentum = current - previous
        
        if current > 4.0:
            trend = "高位"
        elif current < 1.0:
            trend = "低位"
        elif momentum > 0.2:
            trend = "上升"
        elif momentum < -0.2:
            trend = "下降"
        else:
            trend = "稳定"
            
        return current, trend, momentum

    def _analyze_pmi_data(self, data: List[Dict]) -> Tuple[float, str, float]:
        """分析PMI数据"""
        if not data or len(data) < 2:
            return 50.0, ">50", 0.0
            
        current = data[0]["value"]
        previous = data[1]["value"]
        momentum = current - previous
        
        if current >= 52:
            trend = ">52"
        elif current >= 50:
            trend = ">50"
        elif current >= 48:
            trend = "<50"
        else:
            trend = "<48"
            
        return current, trend, momentum

    def _analyze_bdi_data(self, data: List[Dict]) -> Tuple[float, str]:
        """分析BDI数据"""
        if not data or len(data) < 2:
            return 1200.0, "稳定"
            
        current = data[0]["value"]
        previous = data[1]["value"]
        
        change_pct = (current - previous) / previous * 100
        
        if change_pct > 5:
            trend = "强劲上升"
        elif change_pct > 2:
            trend = "上升"
        elif change_pct < -5:
            trend = "大幅下降"
        elif change_pct < -2:
            trend = "下降"
        else:
            trend = "稳定"
            
        return current, trend

    # 条件匹配方法
    def _match_ppi_condition(self, value: float, trend: str, momentum: float, condition: Dict) -> bool:
        """匹配PPI条件"""
        if "trend" in condition and condition["trend"] != trend:
            return False
        if "threshold" in condition and value < condition["threshold"]:
            return False
        if "from_high" in condition and condition["from_high"] and momentum >= 0:
            return False
        if "negative" in condition and condition["negative"] and value >= 0:
            return False
        if "deep_negative" in condition and condition["deep_negative"] and value >= -1.0:
            return False
        return True

    def _match_cpi_condition(self, value: float, trend: str, momentum: float, condition: Dict) -> bool:
        """匹配CPI条件"""
        if "trend" in condition and condition["trend"] != trend:
            return False
        if "range" in condition:
            min_val, max_val = condition["range"]
            if not (min_val <= value <= max_val):
                return False
        if "threshold" in condition and value < condition["threshold"]:
            return False
        if "persistent" in condition and condition["persistent"] and abs(momentum) > 0.3:
            return False
        if "deflation_risk" in condition and condition["deflation_risk"] and value > 1.0:
            return False
        return True

    def _match_pmi_condition(self, value: float, trend: str, momentum: float, condition: Dict) -> bool:
        """匹配PMI条件"""
        if "threshold" in condition:
            threshold = condition["threshold"]
            if "below" in condition and condition["below"]:
                if value >= threshold:
                    return False
            else:
                if value < threshold:
                    return False
        if "momentum" in condition:
            if condition["momentum"] == "positive" and momentum <= 0:
                return False
            elif condition["momentum"] == "strong" and momentum < 0.5:
                return False
        if "declining" in condition and condition["declining"] and momentum >= 0:
            return False
        return True

    def _is_compatible_inventory_phase(self, expected: str, actual: str) -> bool:
        """检查库存周期阶段兼容性"""
        compatibility_map = {
            "主动补库存": ["被动补库存"],
            "被动补库存": ["主动补库存", "主动去库存"],
            "主动去库存": ["被动补库存", "被动去库存"],
            "被动去库存": ["主动去库存"]
        }
        return actual in compatibility_map.get(expected, [])

    def _assess_macro_strength(self, indicators: MacroIndicators) -> float:
        """评估宏观指标强度"""
        strength_factors = []
        
        # PPI强度
        if indicators.ppi_trend == "上升" and indicators.ppi_momentum > 0.3:
            strength_factors.append(0.8)
        elif indicators.ppi_trend in ["稳定", "高位"]:
            strength_factors.append(0.6)
        else:
            strength_factors.append(0.3)
            
        # PMI强度
        if indicators.pmi_value > 52:
            strength_factors.append(0.9)
        elif indicators.pmi_value > 50:
            strength_factors.append(0.7)
        elif indicators.pmi_value > 48:
            strength_factors.append(0.4)
        else:
            strength_factors.append(0.2)
            
        # CPI适度性
        if 2.0 <= indicators.cpi_value <= 3.0:
            strength_factors.append(0.8)
        elif indicators.cpi_value > 4.0 or indicators.cpi_value < 1.0:
            strength_factors.append(0.3)
        else:
            strength_factors.append(0.6)
            
        return sum(strength_factors) / len(strength_factors)