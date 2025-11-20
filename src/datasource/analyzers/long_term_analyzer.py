"""
120日背景扫描 - 长期趋势分析器
Long-Term Trend Analyzer for 120-day Background Scanning

实现120日战略级分析框架，包含五大新增模块：
1. 经济周期分析 (Economic Cycle Analysis)
2. 政策跟踪系统 (Policy Tracking)  
3. 国际对比框架 (International Comparison)
4. 行业轮动映射 (Industry Rotation Mapping)
5. 系统性风险预警 (Systemic Risk Warning)
"""

import asyncio
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
from dataclasses import dataclass
import logging

from ..manager import DataSourceManager, get_manager
from ..models.base import DataResponse
from ..calculators.technical_indicators import TechnicalIndicators
from ..calculators.pring_analyzer import PringAnalyzer
from ..config.indices_config import A_SHARE_INDICES, TECHNICAL_PARAMS

logger = logging.getLogger(__name__)

@dataclass
class LongTermTrendResult:
    """长期趋势分析结果"""
    symbol: str
    timeframe: str  # "30d", "120d", "365d"
    trend_score: float  # 趋势评分 0-100
    cycle_stage: str   # 经济周期阶段
    policy_impact: float  # 政策影响评分
    international_rank: int  # 国际排名
    industry_rotation: str  # 行业轮动状态
    risk_level: str   # 风险等级
    confidence: float  # 置信度
    analysis_date: datetime
    raw_data: Dict[str, Any]

@dataclass 
class CycleAnalysis:
    """经济周期分析结果"""
    cycle_stage: str  # "复苏", "扩张", "过热", "滞胀", "衰退", "萧条"
    ppi_trend: str    # PPI趋势
    cpi_trend: str    # CPI趋势  
    pmi_status: str   # PMI状态
    inventory_phase: str  # 库存周期阶段
    cycle_score: float    # 周期评分 0-100
    stage_duration: int   # 当前阶段持续天数
    next_stage_prob: float # 下一阶段概率

class LongTermAnalyzer:
    """120日长期趋势分析器"""
    
    def __init__(self, manager: Optional[DataSourceManager] = None):
        self.manager = manager or get_manager()
        self.tech_indicators = TechnicalIndicators()
        self.pring_analyzer = PringAnalyzer()
        
        # 时间框架权重配置 (来自120日方案设计)
        self.timeframe_weights = {
            "30d": 0.30,   # 30日战术权重
            "120d": 0.50,  # 120日战略权重  
            "365d": 0.20   # 年度验证权重
        }
        
        # 经济周期阶段定义
        self.cycle_stages = {
            "复苏": {"ppi": "上升", "cpi": "稳定", "pmi": ">50", "inventory": "主动补库存"},
            "扩张": {"ppi": "高位", "cpi": "上升", "pmi": ">52", "inventory": "被动补库存"},
            "过热": {"ppi": "下降", "cpi": "高位", "pmi": ">50", "inventory": "主动去库存"},
            "滞胀": {"ppi": "下降", "cpi": "高位", "pmi": "<50", "inventory": "主动去库存"},
            "衰退": {"ppi": "低位", "cpi": "下降", "pmi": "<48", "inventory": "被动去库存"},
            "萧条": {"ppi": "低位", "cpi": "低位", "pmi": "<45", "inventory": "被动去库存"}
        }

    async def analyze_long_term_trend(self, symbol: str, 
                                    end_date: Optional[str] = None) -> LongTermTrendResult:
        """
        执行完整的120日长期趋势分析
        
        Args:
            symbol: 股票/指数代码
            end_date: 结束日期，默认今日
            
        Returns:
            LongTermTrendResult: 长期趋势分析结果
        """
        if not end_date:
            end_date = datetime.now().strftime('%Y-%m-%d')
            
        logger.info(f"Starting 120-day long-term analysis for {symbol}")
        
        try:
            # 并行获取多时间框架数据
            tasks = []
            for timeframe in ["30d", "120d", "365d"]:
                task = self._get_timeframe_data(symbol, timeframe, end_date)
                tasks.append(task)
                
            timeframe_data = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 检查数据获取结果
            data_dict = {}
            for i, (timeframe, data) in enumerate(zip(["30d", "120d", "365d"], timeframe_data)):
                if isinstance(data, Exception):
                    logger.warning(f"Failed to get {timeframe} data for {symbol}: {data}")
                    continue
                data_dict[timeframe] = data
                
            if not data_dict:
                raise ValueError(f"No valid data obtained for {symbol}")
            
            # 执行五大模块分析
            cycle_analysis = await self._analyze_economic_cycle(symbol, data_dict, end_date)
            policy_impact = await self._analyze_policy_impact(symbol, data_dict, end_date)
            intl_comparison = await self._analyze_international_comparison(symbol, data_dict, end_date)
            industry_rotation = await self._analyze_industry_rotation(symbol, data_dict, end_date)
            risk_warning = await self._analyze_systemic_risk(symbol, data_dict, end_date)
            
            # 综合评分计算
            trend_score = self._calculate_composite_score(
                cycle_analysis, policy_impact, intl_comparison, 
                industry_rotation, risk_warning, data_dict
            )
            
            # 置信度评估
            confidence = self._calculate_confidence(data_dict, cycle_analysis)
            
            result = LongTermTrendResult(
                symbol=symbol,
                timeframe="120d",
                trend_score=trend_score,
                cycle_stage=cycle_analysis.cycle_stage,
                policy_impact=policy_impact,
                international_rank=intl_comparison,
                industry_rotation=industry_rotation,
                risk_level=risk_warning,
                confidence=confidence,
                analysis_date=datetime.now(),
                raw_data={
                    "cycle_analysis": cycle_analysis,
                    "timeframe_data": data_dict,
                    "weights": self.timeframe_weights
                }
            )
            
            logger.info(f"Completed 120-day analysis for {symbol}: score={trend_score:.1f}, confidence={confidence:.1f}%")
            return result
            
        except Exception as e:
            logger.error(f"Long-term analysis failed for {symbol}: {e}")
            raise

    async def _get_timeframe_data(self, symbol: str, timeframe: str, end_date: str) -> pd.DataFrame:
        """获取指定时间框架的数据"""
        days_map = {"30d": 45, "120d": 150, "365d": 400}  # 增加缓冲天数
        days = days_map.get(timeframe, 150)
        
        start_date = (datetime.strptime(end_date, '%Y-%m-%d') - timedelta(days=days)).strftime('%Y-%m-%d')
        
        response = await self.manager.get_stock_daily(symbol, start_date, end_date)
        if response.error:
            raise ValueError(f"Failed to get {timeframe} data: {response.error}")
            
        return response.data

    async def _analyze_economic_cycle(self, symbol: str, data_dict: Dict, end_date: str) -> CycleAnalysis:
        """
        模块1: 经济周期分析
        基于PPI、CPI、PMI数据判断经济周期阶段
        """
        try:
            # 获取宏观经济数据
            macro_data = await self._get_macro_economic_data(end_date)
            
            # 分析PPI趋势
            ppi_trend = self._analyze_ppi_trend(macro_data.get("ppi", []))
            
            # 分析CPI趋势  
            cpi_trend = self._analyze_cpi_trend(macro_data.get("cpi", []))
            
            # 分析PMI状态
            pmi_status = self._analyze_pmi_status(macro_data.get("pmi", []))
            
            # 判断库存周期阶段
            inventory_phase = self._determine_inventory_phase(ppi_trend, cpi_trend, pmi_status)
            
            # 识别经济周期阶段
            cycle_stage = self._identify_cycle_stage(ppi_trend, cpi_trend, pmi_status, inventory_phase)
            
            # 计算周期评分
            cycle_score = self._calculate_cycle_score(cycle_stage, ppi_trend, cpi_trend, pmi_status)
            
            # 估算阶段持续时间
            stage_duration = self._estimate_stage_duration(cycle_stage, macro_data)
            
            # 预测下一阶段概率
            next_stage_prob = self._predict_next_stage_probability(cycle_stage, stage_duration)
            
            return CycleAnalysis(
                cycle_stage=cycle_stage,
                ppi_trend=ppi_trend,
                cpi_trend=cpi_trend,
                pmi_status=pmi_status,
                inventory_phase=inventory_phase,
                cycle_score=cycle_score,
                stage_duration=stage_duration,
                next_stage_prob=next_stage_prob
            )
            
        except Exception as e:
            logger.warning(f"Economic cycle analysis failed: {e}")
            # 返回默认分析结果
            return CycleAnalysis(
                cycle_stage="未知",
                ppi_trend="数据不足",
                cpi_trend="数据不足", 
                pmi_status="数据不足",
                inventory_phase="数据不足",
                cycle_score=50.0,
                stage_duration=0,
                next_stage_prob=0.5
            )

    async def _analyze_policy_impact(self, symbol: str, data_dict: Dict, end_date: str) -> float:
        """
        模块2: 政策跟踪系统
        分析货币政策、财政政策对市场的影响
        """
        try:
            # 获取政策相关数据
            policy_data = await self._get_policy_data(end_date)
            
            # 分析货币政策影响
            monetary_impact = self._analyze_monetary_policy(policy_data.get("monetary", {}))
            
            # 分析财政政策影响
            fiscal_impact = self._analyze_fiscal_policy(policy_data.get("fiscal", {}))
            
            # 分析监管政策影响
            regulatory_impact = self._analyze_regulatory_policy(policy_data.get("regulatory", {}), symbol)
            
            # 综合政策影响评分
            policy_score = (monetary_impact * 0.4 + fiscal_impact * 0.3 + regulatory_impact * 0.3)
            
            return max(0, min(100, policy_score))
            
        except Exception as e:
            logger.warning(f"Policy impact analysis failed: {e}")
            return 50.0  # 默认中性评分

    async def _analyze_international_comparison(self, symbol: str, data_dict: Dict, end_date: str) -> int:
        """
        模块3: 国际对比框架  
        与主要国际市场指数进行对比分析
        """
        try:
            # 获取国际市场数据
            intl_data = await self._get_international_data(end_date)
            
            # 计算相对表现
            performance_metrics = []
            
            # A股相对表现
            a_share_perf = self._calculate_relative_performance(data_dict.get("120d"), intl_data.get("a_share"))
            
            # 与主要市场对比
            for market, data in intl_data.items():
                if market == "a_share":
                    continue
                relative_perf = self._calculate_relative_performance(data_dict.get("120d"), data)
                performance_metrics.append((market, relative_perf))
                
            # 排名计算
            performance_metrics.sort(key=lambda x: x[1], reverse=True)
            
            # 找到A股排名
            a_share_rank = 1
            for i, (market, perf) in enumerate(performance_metrics, 1):
                if perf < a_share_perf:
                    a_share_rank = i
                    break
            else:
                a_share_rank = len(performance_metrics) + 1
                
            return a_share_rank
            
        except Exception as e:
            logger.warning(f"International comparison failed: {e}")
            return 5  # 默认中等排名

    async def _analyze_industry_rotation(self, symbol: str, data_dict: Dict, end_date: str) -> str:
        """
        模块4: 行业轮动映射
        分析当前行业轮动状态和趋势
        """
        try:
            # 获取行业数据
            industry_data = await self._get_industry_data(end_date)
            
            # 分析各行业相对强度
            industry_strength = self._calculate_industry_strength(industry_data)
            
            # 识别轮动模式
            rotation_pattern = self._identify_rotation_pattern(industry_strength)
            
            # 预测轮动方向
            rotation_direction = self._predict_rotation_direction(industry_strength, rotation_pattern)
            
            # 确定目标股票所在行业的轮动状态
            target_industry = self._get_stock_industry(symbol)
            industry_status = industry_strength.get(target_industry, {})
            
            rotation_state = f"{rotation_pattern}_{rotation_direction}"
            
            return rotation_state
            
        except Exception as e:
            logger.warning(f"Industry rotation analysis failed: {e}")
            return "数据不足_中性"

    async def _analyze_systemic_risk(self, symbol: str, data_dict: Dict, end_date: str) -> str:
        """
        模块5: 系统性风险预警
        评估系统性风险水平
        """
        try:
            # 获取风险指标数据
            risk_data = await self._get_risk_indicators(end_date)
            
            # 分析流动性风险
            liquidity_risk = self._analyze_liquidity_risk(risk_data.get("liquidity", {}))
            
            # 分析信用风险
            credit_risk = self._analyze_credit_risk(risk_data.get("credit", {}))
            
            # 分析市场风险
            market_risk = self._analyze_market_risk(data_dict, risk_data.get("market", {}))
            
            # 分析外部风险
            external_risk = self._analyze_external_risk(risk_data.get("external", {}))
            
            # 综合风险评级
            risk_scores = [liquidity_risk, credit_risk, market_risk, external_risk]
            avg_risk = sum(risk_scores) / len(risk_scores)
            
            if avg_risk >= 80:
                return "极高风险"
            elif avg_risk >= 60:
                return "高风险"
            elif avg_risk >= 40:
                return "中等风险"
            elif avg_risk >= 20:
                return "低风险"
            else:
                return "极低风险"
                
        except Exception as e:
            logger.warning(f"Systemic risk analysis failed: {e}")
            return "中等风险"

    def _calculate_composite_score(self, cycle_analysis: CycleAnalysis, policy_impact: float,
                                 intl_rank: int, industry_rotation: str, risk_level: str,
                                 data_dict: Dict) -> float:
        """计算综合趋势评分"""
        
        # 经济周期评分权重 30%
        cycle_score = cycle_analysis.cycle_score * 0.30
        
        # 政策影响评分权重 25%  
        policy_score = policy_impact * 0.25
        
        # 国际排名评分权重 20% (排名越高分数越高)
        intl_score = max(0, (10 - intl_rank) * 10) * 0.20
        
        # 行业轮动评分权重 15%
        rotation_score = self._score_industry_rotation(industry_rotation) * 0.15
        
        # 风险调整权重 10%
        risk_adjustment = self._score_risk_level(risk_level) * 0.10
        
        composite_score = cycle_score + policy_score + intl_score + rotation_score + risk_adjustment
        
        return max(0, min(100, composite_score))

    def _calculate_confidence(self, data_dict: Dict, cycle_analysis: CycleAnalysis) -> float:
        """计算分析置信度"""
        confidence_factors = []
        
        # 数据完整性
        data_completeness = len(data_dict) / 3 * 100  # 期望3个时间框架
        confidence_factors.append(data_completeness)
        
        # 周期分析置信度
        if cycle_analysis.cycle_stage != "未知":
            confidence_factors.append(80.0)
        else:
            confidence_factors.append(20.0)
            
        # 数据质量评估
        for timeframe, data in data_dict.items():
            if len(data) > 0:
                confidence_factors.append(85.0)
            else:
                confidence_factors.append(10.0)
                
        return sum(confidence_factors) / len(confidence_factors) if confidence_factors else 50.0

    # 辅助方法实现
    async def _get_macro_economic_data(self, end_date: str) -> Dict:
        """获取宏观经济数据"""
        # 模拟实现，实际应调用真实数据源
        return {
            "ppi": [{"date": end_date, "value": 2.5}],
            "cpi": [{"date": end_date, "value": 2.1}], 
            "pmi": [{"date": end_date, "value": 51.2}]
        }

    def _analyze_ppi_trend(self, ppi_data: List) -> str:
        """分析PPI趋势"""
        if not ppi_data or len(ppi_data) < 2:
            return "数据不足"
        
        recent_value = ppi_data[-1]["value"]
        prev_value = ppi_data[-2]["value"]
        
        if recent_value > prev_value + 0.2:
            return "上升"
        elif recent_value < prev_value - 0.2:
            return "下降"
        else:
            return "稳定"

    def _analyze_cpi_trend(self, cpi_data: List) -> str:
        """分析CPI趋势"""
        if not cpi_data or len(cpi_data) < 2:
            return "数据不足"
            
        recent_value = cpi_data[-1]["value"]
        
        if recent_value >= 3.0:
            return "高位"
        elif recent_value <= 1.0:
            return "低位"  
        else:
            return "稳定"

    def _analyze_pmi_status(self, pmi_data: List) -> str:
        """分析PMI状态"""
        if not pmi_data:
            return "数据不足"
            
        recent_value = pmi_data[-1]["value"]
        
        if recent_value >= 52:
            return ">52"
        elif recent_value >= 50:
            return ">50"
        elif recent_value >= 48:
            return "<50"
        else:
            return "<48"

    def _determine_inventory_phase(self, ppi_trend: str, cpi_trend: str, pmi_status: str) -> str:
        """确定库存周期阶段"""
        # 基于PPI、CPI、PMI组合判断库存周期
        if ppi_trend == "上升" and pmi_status in [">50", ">52"]:
            return "主动补库存"
        elif ppi_trend == "下降" and cpi_trend == "上升":
            return "被动补库存"
        elif ppi_trend == "下降" and pmi_status in ["<50", "<48"]:
            return "主动去库存"
        else:
            return "被动去库存"

    def _identify_cycle_stage(self, ppi_trend: str, cpi_trend: str, pmi_status: str, inventory_phase: str) -> str:
        """识别经济周期阶段"""
        for stage, conditions in self.cycle_stages.items():
            matches = 0
            total = len(conditions)
            
            if conditions.get("ppi") == ppi_trend:
                matches += 1
            if conditions.get("cpi") == cpi_trend:
                matches += 1
            if conditions.get("pmi") == pmi_status:
                matches += 1
            if conditions.get("inventory") == inventory_phase:
                matches += 1
                
            if matches >= total * 0.75:  # 75%匹配度
                return stage
                
        return "过渡期"

    def _calculate_cycle_score(self, cycle_stage: str, ppi_trend: str, cpi_trend: str, pmi_status: str) -> float:
        """计算周期评分"""
        stage_scores = {
            "复苏": 75,
            "扩张": 85, 
            "过热": 60,
            "滞胀": 30,
            "衰退": 25,
            "萧条": 20,
            "过渡期": 50,
            "未知": 50
        }
        return stage_scores.get(cycle_stage, 50)

    def _estimate_stage_duration(self, cycle_stage: str, macro_data: Dict) -> int:
        """估算当前阶段持续天数"""
        # 简化实现，实际需要历史数据分析
        return 45  # 默认45天

    def _predict_next_stage_probability(self, cycle_stage: str, duration: int) -> float:
        """预测下一阶段概率"""
        # 基于当前阶段持续时间预测转换概率
        if duration > 90:  # 超过90天，转换概率较高
            return 0.7
        elif duration > 60:
            return 0.5  
        else:
            return 0.3

    async def _get_policy_data(self, end_date: str) -> Dict:
        """获取政策相关数据"""
        # 模拟实现
        return {
            "monetary": {"rate": 4.35, "trend": "stable"},
            "fiscal": {"deficit_ratio": 3.0, "policy": "active"},
            "regulatory": {"sector_policy": "neutral"}
        }

    def _analyze_monetary_policy(self, monetary_data: Dict) -> float:
        """分析货币政策影响"""
        rate = monetary_data.get("rate", 4.0)
        trend = monetary_data.get("trend", "stable")
        
        if trend == "easing":
            return 75.0
        elif trend == "tightening":
            return 30.0
        else:
            return 50.0

    def _analyze_fiscal_policy(self, fiscal_data: Dict) -> float:
        """分析财政政策影响"""
        policy = fiscal_data.get("policy", "neutral")
        
        if policy == "active":
            return 70.0
        elif policy == "tight":
            return 35.0
        else:
            return 50.0

    def _analyze_regulatory_policy(self, regulatory_data: Dict, symbol: str) -> float:
        """分析监管政策影响"""
        sector_policy = regulatory_data.get("sector_policy", "neutral")
        
        if sector_policy == "supportive":
            return 80.0
        elif sector_policy == "restrictive":
            return 25.0
        else:
            return 50.0

    async def _get_international_data(self, end_date: str) -> Dict:
        """获取国际市场数据"""
        # 模拟实现
        return {
            "a_share": {"return": 0.05},
            "us_market": {"return": 0.08},
            "europe_market": {"return": 0.03},
            "japan_market": {"return": 0.02}
        }

    def _calculate_relative_performance(self, local_data: pd.DataFrame, intl_data: Dict) -> float:
        """计算相对表现"""
        if local_data is None or local_data.empty:
            return 0.0
        
        # 计算本地收益率
        local_return = (local_data['close'].iloc[-1] / local_data['close'].iloc[0] - 1) * 100
        
        return local_return

    async def _get_industry_data(self, end_date: str) -> Dict:
        """获取行业数据"""
        # 模拟实现
        return {
            "technology": {"strength": 75},
            "finance": {"strength": 60},
            "healthcare": {"strength": 80},
            "energy": {"strength": 45}
        }

    def _calculate_industry_strength(self, industry_data: Dict) -> Dict:
        """计算行业相对强度"""
        return industry_data

    def _identify_rotation_pattern(self, industry_strength: Dict) -> str:
        """识别轮动模式"""
        strengths = list(industry_strength.values())
        if not strengths:
            return "均衡"
        
        max_strength = max(s.get("strength", 50) for s in strengths)
        min_strength = min(s.get("strength", 50) for s in strengths)
        
        if max_strength - min_strength > 30:
            return "明显分化"
        else:
            return "相对均衡"

    def _predict_rotation_direction(self, industry_strength: Dict, pattern: str) -> str:
        """预测轮动方向"""
        # 简化实现
        return "科技领先"

    def _get_stock_industry(self, symbol: str) -> str:
        """获取股票所属行业"""
        # 简化实现，根据股票代码判断
        if symbol.startswith("00"):
            return "technology"
        elif symbol.startswith("60"):
            return "finance"
        else:
            return "mixed"

    async def _get_risk_indicators(self, end_date: str) -> Dict:
        """获取风险指标数据"""
        # 模拟实现
        return {
            "liquidity": {"vix": 15.5, "spread": 50},
            "credit": {"credit_spread": 120, "default_rate": 1.2},
            "market": {"volatility": 18.5, "correlation": 0.65},
            "external": {"geopolitical": 3.5, "trade": 2.8}
        }

    def _analyze_liquidity_risk(self, liquidity_data: Dict) -> float:
        """分析流动性风险"""
        vix = liquidity_data.get("vix", 20)
        
        if vix > 30:
            return 80.0
        elif vix > 20:
            return 60.0
        else:
            return 40.0

    def _analyze_credit_risk(self, credit_data: Dict) -> float:
        """分析信用风险"""
        credit_spread = credit_data.get("credit_spread", 100)
        
        if credit_spread > 200:
            return 85.0
        elif credit_spread > 150:
            return 65.0
        else:
            return 45.0

    def _analyze_market_risk(self, data_dict: Dict, market_data: Dict) -> float:
        """分析市场风险"""
        volatility = market_data.get("volatility", 20)
        
        if volatility > 25:
            return 75.0
        elif volatility > 20:
            return 55.0
        else:
            return 35.0

    def _analyze_external_risk(self, external_data: Dict) -> float:
        """分析外部风险"""
        geopolitical = external_data.get("geopolitical", 3.0)
        
        if geopolitical > 4.0:
            return 80.0
        elif geopolitical > 3.0:
            return 60.0
        else:
            return 40.0

    def _score_industry_rotation(self, rotation: str) -> float:
        """行业轮动评分"""
        rotation_scores = {
            "明显分化_科技领先": 75,
            "相对均衡_科技领先": 65,
            "明显分化_金融领先": 60,
            "相对均衡_金融领先": 55,
            "数据不足_中性": 50
        }
        return rotation_scores.get(rotation, 50)

    def _score_risk_level(self, risk_level: str) -> float:
        """风险等级评分"""
        risk_scores = {
            "极低风险": 90,
            "低风险": 75,
            "中等风险": 50,
            "高风险": 25,
            "极高风险": 10
        }
        return risk_scores.get(risk_level, 50)

    async def generate_120d_report(self, symbols: List[str], output_file: str = None) -> str:
        """
        生成120日背景扫描报告
        
        Args:
            symbols: 分析标的列表
            output_file: 输出文件路径
            
        Returns:
            报告内容字符串
        """
        report_date = datetime.now().strftime('%Y%m%d')
        if not output_file:
            output_file = f"reports/{report_date}背景扫描120日.md"
            
        logger.info(f"Generating 120-day background scan report for {len(symbols)} symbols")
        
        # 并行分析所有标的
        tasks = [self.analyze_long_term_trend(symbol) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 生成报告内容
        report_content = self._generate_report_content(results, report_date)
        
        # 保存报告
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(report_content)
            logger.info(f"Report saved to {output_file}")
        
        return report_content

    def _generate_report_content(self, results: List, report_date: str) -> str:
        """生成报告内容"""
        content = f"""# 120日背景扫描报告

**报告日期**: {report_date}  
**分析框架**: V2.1 Enhanced Long-term Analysis  
**时间维度**: 120日战略级分析  

## 执行摘要

本报告基于120日背景扫描框架，整合经济周期分析、政策跟踪、国际对比、行业轮动和系统性风险五大模块，为投资决策提供战略级支持。

## 五大模块分析结果

### 1. 经济周期分析模块

"""
        
        # 添加具体分析结果
        valid_results = [r for r in results if not isinstance(r, Exception)]
        
        if valid_results:
            for result in valid_results[:5]:  # 显示前5个结果
                content += f"""
### {result.symbol} 分析结果

- **趋势评分**: {result.trend_score:.1f}/100
- **经济周期**: {result.cycle_stage}
- **政策影响**: {result.policy_impact:.1f}/100
- **国际排名**: {result.international_rank}
- **行业轮动**: {result.industry_rotation}
- **风险等级**: {result.risk_level}
- **置信度**: {result.confidence:.1f}%

"""
        
        content += f"""

## 投资建议

基于120日战略分析框架的综合评估：

1. **战略配置建议**: 根据经济周期阶段调整资产配置
2. **政策响应策略**: 关注政策变化对市场的影响
3. **风险控制措施**: 根据系统性风险等级调整仓位

## 风险提示

本分析基于历史数据和量化模型，不构成投资建议。投资有风险，决策需谨慎。

---
*报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
*分析框架: 120日背景扫描 V2.1*
"""
        
        return content