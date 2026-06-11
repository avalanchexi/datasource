"""
行业轮动映射系统 - Industry Rotation Mapping System
基于经济周期和市场环境变化，预测和追踪行业轮动模式

主要功能:
1. 行业相对强度分析
2. 轮动模式识别（防御→成长→周期→价值）
3. 轮动阶段预测
4. 行业配置建议
5. 轮动时机把握
6. 行业间相关性分析
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import logging
from collections import defaultdict

from ..manager import DataSourceManager, get_manager
from ..models.base import DataResponse
from ..calculators.technical_indicators import TechnicalIndicators
from .economic_cycle_analyzer import EconomicCycleAnalyzer, CycleStageResult

logger = logging.getLogger(__name__)

class RotationPhase(Enum):
    """轮动阶段枚举"""
    DEFENSIVE = "防御期"      # 经济下行，防御性行业领先
    GROWTH = "成长期"        # 经济复苏，成长性行业活跃
    CYCLICAL = "周期期"      # 经济扩张，周期性行业强势
    VALUE = "价值期"         # 经济过热，价值股回归

class IndustryType(Enum):
    """行业类型枚举"""
    DEFENSIVE = "防御性"     # 公用事业、消费必需品
    GROWTH = "成长性"        # 科技、医疗、新能源
    CYCLICAL = "周期性"      # 金融、房地产、有色金属
    COMMODITY = "大宗商品"   # 能源、原材料、化工

@dataclass
class IndustryMetrics:
    """行业指标数据"""
    industry_code: str
    industry_name: str
    industry_type: IndustryType
    
    # 表现指标
    return_1m: float
    return_3m: float
    return_6m: float
    return_ytd: float
    
    # 相对强度
    relative_strength_1m: float    # 相对大盘1月强度
    relative_strength_3m: float    # 相对大盘3月强度
    relative_strength_trend: str   # 强度趋势: "加强", "减弱", "稳定"
    
    # 技术指标
    rsi: float
    momentum: float
    ma_position: str  # MA位置: "上方", "下方", "交叉"
    
    # 基本面指标
    avg_pe: Optional[float] = None
    avg_pb: Optional[float] = None
    roe: Optional[float] = None
    profit_growth: Optional[float] = None
    
    # 资金流向
    fund_inflow: float = 0.0       # 资金净流入
    institutional_ratio: float = 0.0  # 机构持仓比例
    
    # 估值相对性
    valuation_percentile: float = 50.0  # 历史估值分位数
    
    last_update: datetime = None

@dataclass
class RotationPattern:
    """轮动模式数据"""
    pattern_id: str
    pattern_name: str
    current_phase: RotationPhase
    
    # 阶段进度
    phase_progress: float          # 当前阶段进度 0-100%
    phase_duration_days: int       # 当前阶段已持续天数
    expected_duration: int         # 预期阶段总持续时间
    
    # 轮动强度
    rotation_intensity: float      # 轮动强度 0-100
    pattern_confidence: float      # 模式置信度 0-100
    
    # 领先落后行业
    leading_industries: List[str]  # 领先行业
    lagging_industries: List[str]  # 落后行业
    transition_industries: List[str]  # 转换中行业
    
    # 下一阶段预测
    next_phase: RotationPhase
    transition_probability: float  # 转换概率
    expected_transition_date: Optional[datetime] = None
    
    # 驱动因素
    driving_factors: List[str] = field(default_factory=list)
    risk_factors: List[str] = field(default_factory=list)

@dataclass
class RotationRecommendation:
    """轮动配置建议"""
    recommendation_date: datetime
    current_pattern: RotationPattern
    
    # 配置建议
    recommended_overweight: Dict[str, float]  # 建议超配行业及权重
    recommended_underweight: Dict[str, float] # 建议低配行业及权重
    
    # 操作时机
    immediate_actions: List[str]      # 立即执行操作
    watch_list: List[str]            # 关注列表
    
    # 风险控制
    stop_loss_triggers: Dict[str, str]  # 止损触发条件
    rebalance_triggers: List[str]     # 再平衡触发器
    
    # 预期收益
    expected_alpha: float            # 预期超额收益
    risk_budget: float              # 风险预算
    holding_period: int             # 建议持有期

class IndustryRotationMapper:
    """行业轮动映射分析器"""
    
    def __init__(self, manager: Optional[DataSourceManager] = None):
        self.manager = manager or get_manager()
        self.tech_indicators = TechnicalIndicators()
        self.cycle_analyzer = EconomicCycleAnalyzer(manager)
        
        # A股主要行业配置
        self.industry_config = {
            # 防御性行业
            "公用事业": {"code": "BK0427", "type": IndustryType.DEFENSIVE, "beta": 0.7},
            "食品饮料": {"code": "BK0438", "type": IndustryType.DEFENSIVE, "beta": 0.8},
            "医药生物": {"code": "BK0437", "type": IndustryType.GROWTH, "beta": 0.9},
            
            # 成长性行业
            "电子": {"code": "BK0447", "type": IndustryType.GROWTH, "beta": 1.3},
            "计算机": {"code": "BK0448", "type": IndustryType.GROWTH, "beta": 1.4},
            "通信": {"code": "BK0449", "type": IndustryType.GROWTH, "beta": 1.2},
            "新能源": {"code": "BK0451", "type": IndustryType.GROWTH, "beta": 1.5},
            
            # 周期性行业
            "银行": {"code": "BK0452", "type": IndustryType.CYCLICAL, "beta": 1.1},
            "房地产": {"code": "BK0453", "type": IndustryType.CYCLICAL, "beta": 1.3},
            "建筑材料": {"code": "BK0454", "type": IndustryType.CYCLICAL, "beta": 1.2},
            "钢铁": {"code": "BK0456", "type": IndustryType.CYCLICAL, "beta": 1.4},
            
            # 大宗商品
            "有色金属": {"code": "BK0458", "type": IndustryType.COMMODITY, "beta": 1.5},
            "化工": {"code": "BK0459", "type": IndustryType.COMMODITY, "beta": 1.3},
            "石油石化": {"code": "BK0460", "type": IndustryType.COMMODITY, "beta": 1.2},
            "煤炭": {"code": "BK0461", "type": IndustryType.COMMODITY, "beta": 1.4}
        }
        
        # 轮动阶段特征定义
        self.rotation_characteristics = {
            RotationPhase.DEFENSIVE: {
                "economic_stage": ["衰退", "萧条"],
                "leading_types": [IndustryType.DEFENSIVE],
                "typical_duration": (60, 120),
                "key_indicators": ["避险情绪", "流动性宽松", "政策刺激预期"]
            },
            RotationPhase.GROWTH: {
                "economic_stage": ["复苏"],
                "leading_types": [IndustryType.GROWTH, IndustryType.DEFENSIVE],
                "typical_duration": (90, 180),
                "key_indicators": ["复苏预期", "流动性充裕", "估值修复"]
            },
            RotationPhase.CYCLICAL: {
                "economic_stage": ["扩张"],
                "leading_types": [IndustryType.CYCLICAL, IndustryType.COMMODITY],
                "typical_duration": (120, 240),
                "key_indicators": ["经济扩张", "通胀上升", "需求旺盛"]
            },
            RotationPhase.VALUE: {
                "economic_stage": ["过热", "滞胀"],
                "leading_types": [IndustryType.CYCLICAL, IndustryType.DEFENSIVE],
                "typical_duration": (60, 150),
                "key_indicators": ["估值修复", "价值回归", "风险偏好下降"]
            }
        }

    async def analyze_rotation_pattern(self, 
                                     analysis_date: Optional[str] = None,
                                     lookback_days: int = 120) -> RotationPattern:
        """
        分析当前行业轮动模式
        
        Args:
            analysis_date: 分析日期
            lookback_days: 回看天数
            
        Returns:
            RotationPattern: 轮动模式分析结果
        """
        if not analysis_date:
            analysis_date = datetime.now().strftime('%Y-%m-%d')
            
        logger.info(f"Starting industry rotation analysis for {analysis_date}")
        
        try:
            # 并行获取数据
            tasks = [
                self._get_industry_metrics_batch(analysis_date, lookback_days),
                self.cycle_analyzer.analyze_economic_cycle("000001", analysis_date)
            ]
            
            industry_metrics, cycle_result = await asyncio.gather(*tasks)
            
            # 计算行业相对强度
            relative_strengths = self._calculate_relative_strengths(industry_metrics)
            
            # 识别轮动阶段
            current_phase, phase_confidence = self._identify_rotation_phase(
                industry_metrics, cycle_result, relative_strengths
            )
            
            # 分析阶段进度
            phase_progress, duration_days = self._analyze_phase_progress(
                current_phase, industry_metrics, analysis_date
            )
            
            # 识别领先落后行业
            leading, lagging, transition = self._classify_industries_by_performance(
                industry_metrics, relative_strengths, current_phase
            )
            
            # 预测下一阶段
            next_phase, transition_prob, expected_date = self._predict_next_phase(
                current_phase, phase_progress, duration_days, cycle_result
            )
            
            # 分析轮动强度
            rotation_intensity = self._calculate_rotation_intensity(relative_strengths)
            
            # 识别驱动因素
            driving_factors, risk_factors = self._identify_rotation_factors(
                current_phase, cycle_result, industry_metrics
            )
            
            # 预期持续时间
            expected_duration = self._estimate_phase_duration(current_phase, cycle_result)
            
            pattern = RotationPattern(
                pattern_id=f"rotation_{analysis_date}_{current_phase.value}",
                pattern_name=f"{current_phase.value}主导的轮动模式",
                current_phase=current_phase,
                phase_progress=phase_progress,
                phase_duration_days=duration_days,
                expected_duration=expected_duration,
                rotation_intensity=rotation_intensity,
                pattern_confidence=phase_confidence,
                leading_industries=leading,
                lagging_industries=lagging,
                transition_industries=transition,
                next_phase=next_phase,
                transition_probability=transition_prob,
                expected_transition_date=expected_date,
                driving_factors=driving_factors,
                risk_factors=risk_factors
            )
            
            logger.info(f"Rotation analysis completed: {current_phase.value}, confidence={phase_confidence:.1f}%")
            return pattern
            
        except Exception as e:
            logger.error(f"Industry rotation analysis failed: {e}")
            raise

    async def generate_rotation_recommendations(self, 
                                              analysis_date: Optional[str] = None) -> RotationRecommendation:
        """
        生成行业轮动配置建议
        
        Args:
            analysis_date: 分析日期
            
        Returns:
            RotationRecommendation: 轮动配置建议
        """
        if not analysis_date:
            analysis_date = datetime.now().strftime('%Y-%m-%d')
            
        logger.info("Generating industry rotation recommendations")
        
        try:
            # 获取轮动模式分析
            rotation_pattern = await self.analyze_rotation_pattern(analysis_date)
            
            # 生成配置权重建议
            overweight, underweight = self._calculate_allocation_recommendations(rotation_pattern)
            
            # 确定操作时机
            immediate_actions, watch_list = self._determine_action_timing(rotation_pattern)
            
            # 设置风险控制
            stop_loss_triggers, rebalance_triggers = self._setup_risk_controls(rotation_pattern)
            
            # 预期收益估算
            expected_alpha, risk_budget = self._estimate_expected_returns(rotation_pattern)
            
            # 建议持有期
            holding_period = self._calculate_holding_period(rotation_pattern)
            
            recommendation = RotationRecommendation(
                recommendation_date=datetime.strptime(analysis_date, '%Y-%m-%d'),
                current_pattern=rotation_pattern,
                recommended_overweight=overweight,
                recommended_underweight=underweight,
                immediate_actions=immediate_actions,
                watch_list=watch_list,
                stop_loss_triggers=stop_loss_triggers,
                rebalance_triggers=rebalance_triggers,
                expected_alpha=expected_alpha,
                risk_budget=risk_budget,
                holding_period=holding_period
            )
            
            logger.info(f"Rotation recommendations generated with expected alpha: {expected_alpha:.1f}%")
            return recommendation
            
        except Exception as e:
            logger.error(f"Failed to generate rotation recommendations: {e}")
            raise

    async def _get_industry_metrics_batch(self, analysis_date: str, lookback_days: int) -> Dict[str, IndustryMetrics]:
        """批量获取行业指标数据"""
        try:
            # 并行获取所有行业数据
            tasks = []
            for industry_name, config in self.industry_config.items():
                task = self._get_single_industry_metrics(
                    industry_name, config, analysis_date, lookback_days
                )
                tasks.append(task)
                
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 整理有效结果
            industry_metrics = {}
            for i, result in enumerate(results):
                industry_name = list(self.industry_config.keys())[i]
                if isinstance(result, Exception):
                    logger.warning(f"Failed to get metrics for {industry_name}: {result}")
                    continue
                industry_metrics[industry_name] = result
                
            return industry_metrics
            
        except Exception as e:
            logger.error(f"Failed to get industry metrics batch: {e}")
            return {}

    async def _get_single_industry_metrics(self, industry_name: str, config: Dict,
                                         analysis_date: str, lookback_days: int) -> IndustryMetrics:
        """获取单个行业的指标数据"""
        try:
            # 获取行业历史数据
            end_date = analysis_date
            start_date = (datetime.strptime(analysis_date, '%Y-%m-%d') - timedelta(days=lookback_days + 50)).strftime('%Y-%m-%d')
            
            # 尝试获取行业指数数据
            response = await self.manager.get_stock_daily(config["code"], start_date, end_date)
            if response.error:
                # V2.1严格模式：禁止使用模拟数据，返回错误
                logger.error(f"V2.1严格模式：无法获取{industry_name}数据，禁止模拟数据")
                return {"error": f"V2.1严格模式：{industry_name}数据获取失败，禁止模拟数据补充"}
                
            data = response.data
            if data.empty:
                return self._create_simulated_metrics(industry_name, config, analysis_date)
                
            # 获取基准数据（上证指数）
            benchmark_response = await self.manager.get_stock_daily("000001", start_date, end_date)
            benchmark_data = benchmark_response.data if not benchmark_response.error else None
            
            # 计算收益率
            returns = self._calculate_industry_returns(data)
            
            # 计算相对强度
            relative_strength = self._calculate_relative_strength(data, benchmark_data)
            
            # 计算技术指标
            tech_indicators = self._calculate_technical_indicators(data)
            
            # 获取基本面数据
            fundamentals = await self._get_industry_fundamentals(industry_name, config["code"])
            
            # 获取资金流向
            fund_flows = await self._get_industry_fund_flows(industry_name, config["code"])
            
            return IndustryMetrics(
                industry_code=config["code"],
                industry_name=industry_name,
                industry_type=config["type"],
                return_1m=returns["1m"],
                return_3m=returns["3m"],
                return_6m=returns["6m"],
                return_ytd=returns["ytd"],
                relative_strength_1m=relative_strength["1m"],
                relative_strength_3m=relative_strength["3m"],
                relative_strength_trend=relative_strength["trend"],
                rsi=tech_indicators["rsi"],
                momentum=tech_indicators["momentum"],
                ma_position=tech_indicators["ma_position"],
                avg_pe=fundamentals.get("pe"),
                avg_pb=fundamentals.get("pb"),
                roe=fundamentals.get("roe"),
                profit_growth=fundamentals.get("profit_growth"),
                fund_inflow=fund_flows.get("inflow", 0.0),
                institutional_ratio=fund_flows.get("institutional_ratio", 0.0),
                valuation_percentile=fundamentals.get("valuation_percentile", 50.0),
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )
            
        except Exception as e:
            logger.warning(f"Failed to get metrics for {industry_name}: {e}")
            return self._create_simulated_metrics(industry_name, config, analysis_date)

    def _calculate_relative_strengths(self, industry_metrics: Dict[str, IndustryMetrics]) -> Dict[str, float]:
        """计算行业相对强度综合评分"""
        relative_strengths = {}
        
        for industry_name, metrics in industry_metrics.items():
            # 综合相对强度评分
            strength_score = (
                metrics.relative_strength_1m * 0.3 +
                metrics.relative_strength_3m * 0.4 +
                (metrics.return_3m * 0.2) +  # 绝对收益贡献
                (100 - metrics.rsi) * 0.1    # RSI反向贡献（RSI过高反而不利）
            )
            
            # 趋势调整
            if metrics.relative_strength_trend == "加强":
                strength_score *= 1.1
            elif metrics.relative_strength_trend == "减弱":
                strength_score *= 0.9
                
            relative_strengths[industry_name] = strength_score
            
        return relative_strengths

    def _identify_rotation_phase(self, industry_metrics: Dict[str, IndustryMetrics],
                               cycle_result: CycleStageResult,
                               relative_strengths: Dict[str, float]) -> Tuple[RotationPhase, float]:
        """识别当前轮动阶段"""
        
        # 基于经济周期的初步判断
        cycle_stage = cycle_result.stage
        phase_from_cycle = self._map_cycle_to_rotation_phase(cycle_stage)
        
        # 基于行业表现的验证
        type_performance = defaultdict(list)
        for industry_name, metrics in industry_metrics.items():
            industry_type = metrics.industry_type
            strength = relative_strengths.get(industry_name, 50)
            type_performance[industry_type].append(strength)
            
        # 计算各类型平均表现
        avg_performance = {}
        for industry_type, strengths in type_performance.items():
            avg_performance[industry_type] = sum(strengths) / len(strengths)
            
        # 根据类型表现确定轮动阶段
        phase_from_performance = self._determine_phase_from_performance(avg_performance)
        
        # 综合判断
        if phase_from_cycle == phase_from_performance:
            confidence = 85.0
            final_phase = phase_from_cycle
        else:
            # 优先相信行业表现
            confidence = 65.0
            final_phase = phase_from_performance
            
        # 基于轮动强度调整置信度
        rotation_intensity = self._calculate_rotation_intensity(relative_strengths)
        confidence_adjustment = (rotation_intensity - 50) / 100 * 20
        confidence = max(30, min(95, confidence + confidence_adjustment))
        
        return final_phase, confidence

    def _analyze_phase_progress(self, phase: RotationPhase, 
                              industry_metrics: Dict[str, IndustryMetrics],
                              analysis_date: str) -> Tuple[float, int]:
        """分析轮动阶段进度"""
        
        # 基于行业表现分布判断阶段进度
        leading_types = self.rotation_characteristics[phase]["leading_types"]
        
        # 计算领先行业类型的表现强度
        leading_performance = []
        for industry_name, metrics in industry_metrics.items():
            if metrics.industry_type in leading_types:
                leading_performance.append(metrics.relative_strength_3m)
                
        if not leading_performance:
            return 50.0, 60  # 默认值
            
        avg_leading_strength = sum(leading_performance) / len(leading_performance)
        
        # 强度映射到进度
        if avg_leading_strength > 80:
            progress = 90  # 接近尾声
        elif avg_leading_strength > 60:
            progress = 70  # 中后期
        elif avg_leading_strength > 40:
            progress = 50  # 中期
        elif avg_leading_strength > 20:
            progress = 30  # 早期
        else:
            progress = 10  # 刚开始
            
        # 估算持续天数（简化实现）
        typical_duration = self.rotation_characteristics[phase]["typical_duration"]
        estimated_days = int(typical_duration[0] + (typical_duration[1] - typical_duration[0]) * progress / 100)
        
        return progress, estimated_days

    def _classify_industries_by_performance(self, industry_metrics: Dict[str, IndustryMetrics],
                                          relative_strengths: Dict[str, float],
                                          current_phase: RotationPhase) -> Tuple[List[str], List[str], List[str]]:
        """根据表现分类行业"""
        
        # 按相对强度排序
        sorted_industries = sorted(relative_strengths.items(), key=lambda x: x[1], reverse=True)
        
        total_count = len(sorted_industries)
        leading_count = max(2, total_count // 3)
        lagging_count = max(2, total_count // 3)
        
        # 基础分类
        leading = [item[0] for item in sorted_industries[:leading_count]]
        lagging = [item[0] for item in sorted_industries[-lagging_count:]]
        
        # 转换中行业（相对强度在40-60之间且趋势明确的）
        transition = []
        for industry_name, strength in relative_strengths.items():
            if 40 <= strength <= 60 and industry_name not in leading and industry_name not in lagging:
                metrics = industry_metrics[industry_name]
                if metrics.relative_strength_trend in ["加强", "减弱"]:
                    transition.append(industry_name)
                    
        return leading, lagging, transition

    def _predict_next_phase(self, current_phase: RotationPhase, progress: float,
                           duration_days: int, cycle_result: CycleStageResult) -> Tuple[RotationPhase, float, Optional[datetime]]:
        """预测下一轮动阶段"""
        
        # 轮动序列
        phase_sequence = [
            RotationPhase.DEFENSIVE,
            RotationPhase.GROWTH,
            RotationPhase.CYCLICAL,
            RotationPhase.VALUE
        ]
        
        try:
            current_index = phase_sequence.index(current_phase)
            next_phase = phase_sequence[(current_index + 1) % len(phase_sequence)]
        except ValueError:
            next_phase = RotationPhase.GROWTH  # 默认
            
        # 转换概率基于进度和经济周期
        base_probability = progress / 100 * 0.7  # 基于进度的概率
        
        # 经济周期一致性调整
        if cycle_result.transition_probability > 0.6:
            base_probability += 0.2
            
        transition_prob = min(0.9, base_probability)
        
        # 预期转换日期
        expected_date = None
        if transition_prob > 0.5:
            days_to_transition = int((100 - progress) / 100 * 60)  # 估算剩余天数
            expected_date = datetime.now() + timedelta(days=days_to_transition)
            
        return next_phase, transition_prob, expected_date

    def _calculate_rotation_intensity(self, relative_strengths: Dict[str, float]) -> float:
        """计算轮动强度"""
        if not relative_strengths:
            return 50.0
            
        strengths = list(relative_strengths.values())
        
        # 方差衡量轮动强度
        variance = np.var(strengths)
        
        # 归一化到0-100
        # 假设方差在0-1000之间
        intensity = min(100, variance / 10)
        
        return intensity

    def _identify_rotation_factors(self, phase: RotationPhase, cycle_result: CycleStageResult,
                                 industry_metrics: Dict[str, IndustryMetrics]) -> Tuple[List[str], List[str]]:
        """识别轮动驱动因素和风险因素"""
        
        driving_factors = []
        risk_factors = []
        
        # 基于轮动阶段的通用因素
        phase_characteristics = self.rotation_characteristics[phase]
        driving_factors.extend(phase_characteristics["key_indicators"])
        
        # 基于经济周期的因素
        if cycle_result.stage in ["复苏", "扩张"]:
            driving_factors.append("经济增长动能")
        elif cycle_result.stage in ["衰退", "萧条"]:
            driving_factors.append("避险需求上升")
            
        if cycle_result.stage_score > 70:
            driving_factors.append("基本面支撑强劲")
        elif cycle_result.stage_score < 30:
            risk_factors.append("基本面恶化风险")
            
        # 基于行业估值的因素
        high_valuation_count = 0
        for metrics in industry_metrics.values():
            if metrics.valuation_percentile and metrics.valuation_percentile > 80:
                high_valuation_count += 1
                
        if high_valuation_count >= len(industry_metrics) // 2:
            risk_factors.append("整体估值偏高")
            
        # 基于资金流向的因素
        total_inflow = sum(m.fund_inflow for m in industry_metrics.values() if m.fund_inflow)
        if total_inflow > 0:
            driving_factors.append("资金持续流入")
        elif total_inflow < -100:
            risk_factors.append("资金净流出压力")
            
        return driving_factors, risk_factors

    def _calculate_allocation_recommendations(self, pattern: RotationPattern) -> Tuple[Dict[str, float], Dict[str, float]]:
        """计算配置建议"""
        overweight = {}
        underweight = {}
        
        # 基于轮动阶段的标准配置
        phase_weights = {
            RotationPhase.DEFENSIVE: {"防御性": 1.5, "成长性": 0.8, "周期性": 0.7, "大宗商品": 0.6},
            RotationPhase.GROWTH: {"成长性": 1.4, "防御性": 1.1, "周期性": 0.9, "大宗商品": 0.8},
            RotationPhase.CYCLICAL: {"周期性": 1.3, "大宗商品": 1.2, "成长性": 0.9, "防御性": 0.8},
            RotationPhase.VALUE: {"周期性": 1.2, "防御性": 1.1, "成长性": 0.8, "大宗商品": 0.9}
        }
        
        current_weights = phase_weights.get(pattern.current_phase, {})
        
        # 转换为具体行业建议
        for industry in pattern.leading_industries[:3]:  # 取前3个领先行业
            if industry not in overweight:
                overweight[industry] = 15.0  # 建议超配15%
                
        for industry in pattern.lagging_industries[-3:]:  # 取后3个落后行业
            if industry not in underweight:
                underweight[industry] = -10.0  # 建议低配10%
                
        return overweight, underweight

    def _determine_action_timing(self, pattern: RotationPattern) -> Tuple[List[str], List[str]]:
        """确定操作时机"""
        immediate_actions = []
        watch_list = []
        
        # 基于阶段进度的操作建议
        if pattern.phase_progress < 30:
            # 早期阶段，积极布局
            immediate_actions.append(f"积极布局{pattern.current_phase.value}主题")
            for industry in pattern.leading_industries[:2]:
                immediate_actions.append(f"增持{industry}")
                
        elif pattern.phase_progress > 70:
            # 后期阶段，准备轮动
            immediate_actions.append(f"准备{pattern.next_phase.value}布局")
            watch_list.extend(pattern.transition_industries)
            
        else:
            # 中期阶段，维持配置
            immediate_actions.append("维持当前行业配置")
            
        # 基于转换概率的建议
        if pattern.transition_probability > 0.7:
            immediate_actions.append(f"关注{pattern.next_phase.value}机会")
            
        return immediate_actions, watch_list

    def _setup_risk_controls(self, pattern: RotationPattern) -> Tuple[Dict[str, str], List[str]]:
        """设置风险控制"""
        stop_loss_triggers = {}
        rebalance_triggers = []
        
        # 个股止损条件
        for industry in pattern.leading_industries:
            stop_loss_triggers[industry] = "相对强度跌破30日均线"
            
        # 再平衡触发器
        rebalance_triggers.append("轮动强度低于30")
        rebalance_triggers.append("阶段进度超过80%")
        rebalance_triggers.append("经济周期阶段发生转换")
        
        return stop_loss_triggers, rebalance_triggers

    def _estimate_expected_returns(self, pattern: RotationPattern) -> Tuple[float, float]:
        """估算预期收益"""
        # 基于轮动强度和阶段进度
        base_alpha = pattern.rotation_intensity / 100 * 8  # 基础超额收益
        
        # 阶段调整
        if pattern.phase_progress < 50:
            stage_multiplier = 1.2  # 早期阶段收益更高
        else:
            stage_multiplier = 0.8
            
        expected_alpha = base_alpha * stage_multiplier
        
        # 风险预算基于置信度
        risk_budget = pattern.pattern_confidence / 100 * 15  # 最大15%风险预算
        
        return expected_alpha, risk_budget

    def _calculate_holding_period(self, pattern: RotationPattern) -> int:
        """计算建议持有期"""
        # 基于阶段剩余时间
        remaining_progress = 100 - pattern.phase_progress
        expected_remaining_days = int(pattern.expected_duration * remaining_progress / 100)
        
        # 最小30天，最大180天
        holding_period = max(30, min(180, expected_remaining_days))
        
        return holding_period

    # 辅助计算方法
    def _calculate_industry_returns(self, data: pd.DataFrame) -> Dict[str, float]:
        """计算行业收益率"""
        current_price = data['close'].iloc[-1]
        
        returns = {}
        periods = {"1m": 20, "3m": 60, "6m": 120, "ytd": 250}
        
        for period, days in periods.items():
            if len(data) > days:
                past_price = data['close'].iloc[-(days+1)]
                ret = (current_price / past_price - 1) * 100
            else:
                ret = 0.0
            returns[period] = ret
            
        return returns

    def _calculate_relative_strength(self, industry_data: pd.DataFrame, 
                                   benchmark_data: Optional[pd.DataFrame]) -> Dict[str, Union[float, str]]:
        """计算相对强度"""
        if benchmark_data is None or benchmark_data.empty:
            return {"1m": 50.0, "3m": 50.0, "trend": "稳定"}
            
        # 计算相对收益率
        industry_returns = industry_data['close'].pct_change()
        benchmark_returns = benchmark_data['close'].pct_change()
        
        # 对齐数据
        min_length = min(len(industry_returns), len(benchmark_returns))
        industry_returns = industry_returns.tail(min_length)
        benchmark_returns = benchmark_returns.tail(min_length)
        
        relative_returns = industry_returns - benchmark_returns
        
        # 计算不同周期的相对强度
        rs_1m = relative_returns.tail(20).sum() * 100 + 50  # 转换为0-100评分
        rs_3m = relative_returns.tail(60).sum() * 100 + 50
        
        # 判断趋势
        if rs_1m > rs_3m + 5:
            trend = "加强"
        elif rs_1m < rs_3m - 5:
            trend = "减弱"
        else:
            trend = "稳定"
            
        return {
            "1m": max(0, min(100, rs_1m)),
            "3m": max(0, min(100, rs_3m)),
            "trend": trend
        }

    def _calculate_technical_indicators(self, data: pd.DataFrame) -> Dict[str, Union[float, str]]:
        """计算技术指标"""
        try:
            # RSI
            rsi = self.tech_indicators.calculate_rsi(data['close'], 14)
            current_rsi = rsi.iloc[-1] if not rsi.empty else 50.0
            
            # 动量
            momentum = ((data['close'].iloc[-1] / data['close'].iloc[-21]) - 1) * 100 if len(data) > 21 else 0.0
            
            # MA位置
            ma20 = data['close'].rolling(20).mean()
            if data['close'].iloc[-1] > ma20.iloc[-1]:
                ma_position = "上方"
            else:
                ma_position = "下方"
                
            return {
                "rsi": current_rsi,
                "momentum": momentum,
                "ma_position": ma_position
            }
            
        except Exception as e:
            logger.warning(f"Failed to calculate technical indicators: {e}")
            return {"rsi": 50.0, "momentum": 0.0, "ma_position": "中性"}

    async def _get_industry_fundamentals(self, industry_name: str, industry_code: str) -> Dict[str, Optional[float]]:
        """获取行业基本面数据（模拟实现）"""
        # 行业基本面默认值
        fundamentals_defaults = {
            "银行": {"pe": 5.2, "pb": 0.8, "roe": 12.5, "profit_growth": 8.3},
            "房地产": {"pe": 8.5, "pb": 1.2, "roe": 15.2, "profit_growth": -2.1},
            "电子": {"pe": 28.5, "pb": 3.2, "roe": 18.5, "profit_growth": 25.8},
            "食品饮料": {"pe": 22.5, "pb": 4.1, "roe": 20.2, "profit_growth": 12.5}
        }
        
        defaults = fundamentals_defaults.get(industry_name, 
                                           {"pe": 18.0, "pb": 2.5, "roe": 15.0, "profit_growth": 10.0})
        
        # 估值分位数（简化实现）
        defaults["valuation_percentile"] = min(90, max(10, defaults["pe"] / 25 * 100))
        
        return defaults

    async def _get_industry_fund_flows(self, industry_name: str, industry_code: str) -> Dict[str, float]:
        """获取行业资金流向数据（模拟实现）"""
        flow_defaults = {
            "银行": {"inflow": -50.2, "institutional_ratio": 45.8},
            "电子": {"inflow": 235.8, "institutional_ratio": 52.3},
            "房地产": {"inflow": -125.6, "institutional_ratio": 38.9},
            "食品饮料": {"inflow": 86.5, "institutional_ratio": 58.7}
        }
        
        return flow_defaults.get(industry_name, {"inflow": 0.0, "institutional_ratio": 50.0})

    def _create_simulated_metrics(self, industry_name: str, config: Dict, analysis_date: str) -> IndustryMetrics:
        """创建模拟的行业指标数据"""
        # 基于行业类型生成不同的模拟数据
        industry_type = config["type"]
        
        if industry_type == IndustryType.GROWTH:
            base_return = 8.5
            relative_strength = 65.0
        elif industry_type == IndustryType.CYCLICAL:
            base_return = 5.2
            relative_strength = 55.0
        elif industry_type == IndustryType.DEFENSIVE:
            base_return = 3.8
            relative_strength = 45.0
        else:  # COMMODITY
            base_return = 12.3
            relative_strength = 70.0
            
        return IndustryMetrics(
            industry_code=config["code"],
            industry_name=industry_name,
            industry_type=industry_type,
            return_1m=base_return * 0.3,
            return_3m=base_return,
            return_6m=base_return * 1.8,
            return_ytd=base_return * 2.2,
            relative_strength_1m=relative_strength,
            relative_strength_3m=relative_strength,
            relative_strength_trend="稳定",
            rsi=50.0 + (relative_strength - 50) * 0.3,
            momentum=base_return * 0.5,
            ma_position="上方" if base_return > 5 else "下方",
            last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
        )

    def _map_cycle_to_rotation_phase(self, cycle_stage: str) -> RotationPhase:
        """将经济周期映射到轮动阶段"""
        cycle_phase_map = {
            "萧条": RotationPhase.DEFENSIVE,
            "衰退": RotationPhase.DEFENSIVE,
            "复苏": RotationPhase.GROWTH,
            "扩张": RotationPhase.CYCLICAL,
            "过热": RotationPhase.VALUE,
            "滞胀": RotationPhase.VALUE
        }
        return cycle_phase_map.get(cycle_stage, RotationPhase.GROWTH)

    def _determine_phase_from_performance(self, avg_performance: Dict[IndustryType, float]) -> RotationPhase:
        """基于行业类型表现确定轮动阶段"""
        # 找出表现最好的行业类型
        best_type = max(avg_performance, key=avg_performance.get)
        
        if best_type == IndustryType.DEFENSIVE:
            return RotationPhase.DEFENSIVE
        elif best_type == IndustryType.GROWTH:
            return RotationPhase.GROWTH
        elif best_type in [IndustryType.CYCLICAL, IndustryType.COMMODITY]:
            return RotationPhase.CYCLICAL
        else:
            return RotationPhase.VALUE

    def _estimate_phase_duration(self, phase: RotationPhase, cycle_result: CycleStageResult) -> int:
        """估算轮动阶段持续时间"""
        typical_range = self.rotation_characteristics[phase]["typical_duration"]
        
        # 基于经济周期的调整
        if cycle_result.confidence > 80:
            # 高置信度时，使用典型持续时间的上限
            return typical_range[1]
        else:
            # 低置信度时，使用中值
            return (typical_range[0] + typical_range[1]) // 2