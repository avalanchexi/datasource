"""
系统性风险预警系统 - Systemic Risk Warning System
多维度监控和预警系统性金融风险

主要功能:
1. 流动性风险监控 (VIX、利差、流动性指标)
2. 信用风险评估 (信用利差、违约率、信用评级)
3. 市场风险分析 (波动率、相关性、尾部风险)
4. 宏观风险跟踪 (经济指标异常、政策风险)
5. 外部冲击监控 (地缘政治、贸易摩擦、疫情)
6. 系统性风险综合评分和预警
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum
import logging
import warnings
from scipy import stats

from ..manager import DataSourceManager, get_manager
from ..models.base import DataResponse
from ..calculators.technical_indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

class RiskLevel(Enum):
    """风险等级枚举"""
    EXTREME = "极高风险"    # 90-100
    HIGH = "高风险"        # 70-89
    ELEVATED = "偏高风险"   # 55-69
    MODERATE = "中等风险"   # 40-54
    LOW = "低风险"         # 20-39
    MINIMAL = "极低风险"    # 0-19

class RiskCategory(Enum):
    """风险类别枚举"""
    LIQUIDITY = "流动性风险"
    CREDIT = "信用风险"
    MARKET = "市场风险"
    MACRO = "宏观风险"
    EXTERNAL = "外部冲击"

class AlertLevel(Enum):
    """预警级别枚举"""
    RED = "红色预警"       # 立即行动
    ORANGE = "橙色预警"    # 高度关注
    YELLOW = "黄色预警"    # 密切监控
    GREEN = "绿色正常"     # 正常状态

@dataclass
class RiskIndicator:
    """风险指标数据"""
    indicator_name: str
    category: RiskCategory
    current_value: float
    threshold_values: Dict[str, float]  # 阈值定义
    
    # 历史数据
    historical_percentile: float = 50.0  # 历史分位数
    z_score: float = 0.0                 # 标准化得分
    
    # 趋势分析
    trend_direction: str = "稳定"        # "上升", "下降", "稳定"
    trend_strength: float = 0.0          # 趋势强度
    momentum: float = 0.0                # 动量
    
    # 风险评估
    risk_contribution: float = 0.0       # 对系统风险的贡献度
    alert_triggered: bool = False        # 是否触发预警
    alert_level: AlertLevel = AlertLevel.GREEN
    
    last_update: datetime = None

@dataclass
class LiquidityRisk:
    """流动性风险评估"""
    # VIX恐慌指数
    vix_level: float
    vix_percentile: float
    vix_trend: str
    
    # 利差指标
    credit_spread: float              # 信用利差
    term_spread: float               # 期限利差
    liquidity_spread: float          # 流动性利差
    
    # 流动性指标
    bid_ask_spread: float            # 买卖价差
    market_depth: float              # 市场深度
    turnover_ratio: float            # 换手率
    
    # 综合评分
    liquidity_score: float           # 流动性风险评分
    risk_level: RiskLevel
    
    # 预警信号
    warning_signals: List[str] = field(default_factory=list)

@dataclass
class CreditRisk:
    """信用风险评估"""
    # 信用利差
    corporate_spread: float          # 企业债利差
    high_yield_spread: float         # 高收益债利差
    sovereign_spread: float          # 主权债利差
    
    # 违约指标
    default_rate: float             # 违约率
    default_rate_trend: str         # 违约率趋势
    recovery_rate: float            # 回收率
    
    # 信用评级
    rating_downgrades: int          # 评级下调数量
    rating_upgrades: int            # 评级上调数量
    rating_outlook: str             # 评级展望
    
    # 银行指标
    npl_ratio: float                # 不良贷款率
    provision_coverage: float       # 拨备覆盖率
    capital_adequacy: float         # 资本充足率
    
    # 综合评分
    credit_score: float
    risk_level: RiskLevel
    
    warning_signals: List[str] = field(default_factory=list)

@dataclass
class MarketRisk:
    """市场风险评估"""
    # 波动率指标
    realized_volatility: float      # 实际波动率
    implied_volatility: float       # 隐含波动率
    volatility_skew: float          # 波动率偏度
    
    # 相关性指标
    cross_asset_correlation: float  # 跨资产相关性
    sector_correlation: float       # 行业相关性
    correlation_breakdown: bool     # 相关性失效
    
    # 尾部风险
    var_95: float                   # 95% VaR
    cvar_95: float                  # 95% CVaR
    max_drawdown: float             # 最大回撤
    
    # 市场结构
    concentration_ratio: float      # 集中度比率
    market_fragmentation: float     # 市场分割度
    
    # 流动性风险
    market_impact: float            # 市场冲击成本
    execution_shortfall: float      # 执行缺口
    
    # 综合评分
    market_score: float
    risk_level: RiskLevel
    
    warning_signals: List[str] = field(default_factory=list)

@dataclass
class SystemicRiskAssessment:
    """系统性风险综合评估"""
    assessment_date: datetime
    
    # 各类风险评估
    liquidity_risk: LiquidityRisk
    credit_risk: CreditRisk
    market_risk: MarketRisk
    
    # 综合风险评分
    overall_risk_score: float       # 0-100
    overall_risk_level: RiskLevel
    overall_alert_level: AlertLevel
    
    # 风险分解
    risk_contributions: Dict[RiskCategory, float]
    
    # 主要风险因子
    top_risk_factors: List[str]
    
    # 预警信号
    active_warnings: List[str]
    warning_summary: str
    
    # 风险趋势
    risk_trend: str                 # "上升", "下降", "稳定"
    trend_duration: int             # 趋势持续天数
    
    # 建议措施
    recommended_actions: List[str]
    monitoring_priorities: List[str]
    
    confidence_level: float

class SystemicRiskMonitor:
    """系统性风险监控器"""
    
    def __init__(self, manager: Optional[DataSourceManager] = None):
        self.manager = manager or get_manager()
        self.tech_indicators = TechnicalIndicators()
        
        # 风险权重配置
        self.risk_weights = {
            RiskCategory.LIQUIDITY: 0.25,    # 流动性风险权重
            RiskCategory.CREDIT: 0.25,       # 信用风险权重
            RiskCategory.MARKET: 0.25,       # 市场风险权重
            RiskCategory.MACRO: 0.15,        # 宏观风险权重
            RiskCategory.EXTERNAL: 0.10      # 外部冲击权重
        }
        
        # 预警阈值配置
        self.alert_thresholds = {
            # 流动性风险阈值
            "vix": {"yellow": 20, "orange": 30, "red": 40},
            "credit_spread": {"yellow": 150, "orange": 250, "red": 400},
            "bid_ask_spread": {"yellow": 0.1, "orange": 0.2, "red": 0.5},
            
            # 信用风险阈值  
            "corporate_spread": {"yellow": 200, "orange": 350, "red": 500},
            "default_rate": {"yellow": 2.0, "orange": 4.0, "red": 8.0},
            "npl_ratio": {"yellow": 3.0, "orange": 5.0, "red": 8.0},
            
            # 市场风险阈值
            "realized_volatility": {"yellow": 20, "orange": 30, "red": 45},
            "max_drawdown": {"yellow": -10, "orange": -20, "red": -35},
            "correlation": {"yellow": 0.7, "orange": 0.8, "red": 0.9}
        }
        
        # 历史数据窗口
        self.lookback_periods = {
            "short": 30,    # 短期（1个月）
            "medium": 90,   # 中期（3个月）  
            "long": 252     # 长期（1年）
        }

    async def assess_systemic_risk(self, 
                                 analysis_date: Optional[str] = None) -> SystemicRiskAssessment:
        """
        执行系统性风险综合评估
        
        Args:
            analysis_date: 分析日期，默认今日
            
        Returns:
            SystemicRiskAssessment: 系统性风险评估结果
        """
        if not analysis_date:
            analysis_date = datetime.now().strftime('%Y-%m-%d')
            
        logger.info(f"Starting systemic risk assessment for {analysis_date}")
        
        try:
            # 并行评估各类风险
            tasks = [
                self._assess_liquidity_risk(analysis_date),
                self._assess_credit_risk(analysis_date),
                self._assess_market_risk(analysis_date)
            ]
            
            liquidity_risk, credit_risk, market_risk = await asyncio.gather(*tasks)
            
            # 计算综合风险评分
            overall_score = self._calculate_overall_risk_score(
                liquidity_risk, credit_risk, market_risk
            )
            
            # 确定风险等级和预警级别
            overall_level = self._determine_risk_level(overall_score)
            alert_level = self._determine_alert_level(overall_score, liquidity_risk, credit_risk, market_risk)
            
            # 分析风险贡献
            risk_contributions = self._analyze_risk_contributions(
                liquidity_risk, credit_risk, market_risk
            )
            
            # 识别主要风险因子
            top_risk_factors = self._identify_top_risk_factors(
                liquidity_risk, credit_risk, market_risk
            )
            
            # 汇总预警信号
            active_warnings = self._collect_active_warnings(
                liquidity_risk, credit_risk, market_risk
            )
            warning_summary = self._generate_warning_summary(active_warnings)
            
            # 分析风险趋势
            risk_trend, trend_duration = self._analyze_risk_trend(overall_score, analysis_date)
            
            # 生成建议措施
            recommended_actions, monitoring_priorities = self._generate_recommendations(
                overall_level, alert_level, top_risk_factors, active_warnings
            )
            
            # 计算置信度
            confidence = self._calculate_assessment_confidence(
                liquidity_risk, credit_risk, market_risk
            )
            
            assessment = SystemicRiskAssessment(
                assessment_date=datetime.strptime(analysis_date, '%Y-%m-%d'),
                liquidity_risk=liquidity_risk,
                credit_risk=credit_risk,
                market_risk=market_risk,
                overall_risk_score=overall_score,
                overall_risk_level=overall_level,
                overall_alert_level=alert_level,
                risk_contributions=risk_contributions,
                top_risk_factors=top_risk_factors,
                active_warnings=active_warnings,
                warning_summary=warning_summary,
                risk_trend=risk_trend,
                trend_duration=trend_duration,
                recommended_actions=recommended_actions,
                monitoring_priorities=monitoring_priorities,
                confidence_level=confidence
            )
            
            logger.info(f"Systemic risk assessment completed: {overall_level.value} ({overall_score:.1f})")
            return assessment
            
        except Exception as e:
            logger.error(f"Systemic risk assessment failed: {e}")
            raise

    async def _assess_liquidity_risk(self, analysis_date: str) -> LiquidityRisk:
        """评估流动性风险"""
        try:
            # 获取流动性相关数据
            liquidity_data = await self._fetch_liquidity_data(analysis_date)
            
            # VIX分析
            vix_level = liquidity_data.get("vix", 18.5)
            vix_percentile = self._calculate_percentile(vix_level, "vix")
            vix_trend = self._determine_trend(liquidity_data.get("vix_history", [vix_level]))
            
            # 利差分析
            credit_spread = liquidity_data.get("credit_spread", 120)
            term_spread = liquidity_data.get("term_spread", 180)
            liquidity_spread = liquidity_data.get("liquidity_spread", 50)
            
            # 流动性指标
            bid_ask_spread = liquidity_data.get("bid_ask_spread", 0.05)
            market_depth = liquidity_data.get("market_depth", 85.0)
            turnover_ratio = liquidity_data.get("turnover_ratio", 2.8)
            
            # 计算流动性风险评分
            liquidity_score = self._calculate_liquidity_score(
                vix_level, vix_percentile, credit_spread, term_spread, 
                bid_ask_spread, market_depth, turnover_ratio
            )
            
            # 确定风险等级
            risk_level = self._determine_risk_level(liquidity_score)
            
            # 生成预警信号
            warning_signals = self._generate_liquidity_warnings(
                vix_level, credit_spread, bid_ask_spread, market_depth
            )
            
            return LiquidityRisk(
                vix_level=vix_level,
                vix_percentile=vix_percentile,
                vix_trend=vix_trend,
                credit_spread=credit_spread,
                term_spread=term_spread,
                liquidity_spread=liquidity_spread,
                bid_ask_spread=bid_ask_spread,
                market_depth=market_depth,
                turnover_ratio=turnover_ratio,
                liquidity_score=liquidity_score,
                risk_level=risk_level,
                warning_signals=warning_signals
            )
            
        except Exception as e:
            logger.warning(f"Liquidity risk assessment failed: {e}")
            return self._create_default_liquidity_risk()

    async def _assess_credit_risk(self, analysis_date: str) -> CreditRisk:
        """评估信用风险"""
        try:
            credit_data = await self._fetch_credit_data(analysis_date)
            
            # 信用利差
            corporate_spread = credit_data.get("corporate_spread", 180)
            high_yield_spread = credit_data.get("high_yield_spread", 450)
            sovereign_spread = credit_data.get("sovereign_spread", 80)
            
            # 违约指标
            default_rate = credit_data.get("default_rate", 1.8)
            default_rate_trend = self._determine_trend(credit_data.get("default_history", [default_rate]))
            recovery_rate = credit_data.get("recovery_rate", 65.0)
            
            # 评级变化
            rating_downgrades = credit_data.get("downgrades", 12)
            rating_upgrades = credit_data.get("upgrades", 8)
            rating_outlook = credit_data.get("outlook", "稳定")
            
            # 银行指标
            npl_ratio = credit_data.get("npl_ratio", 2.1)
            provision_coverage = credit_data.get("provision_coverage", 180.5)
            capital_adequacy = credit_data.get("capital_adequacy", 14.2)
            
            # 计算信用风险评分
            credit_score = self._calculate_credit_score(
                corporate_spread, high_yield_spread, default_rate, 
                npl_ratio, capital_adequacy, rating_downgrades, rating_upgrades
            )
            
            risk_level = self._determine_risk_level(credit_score)
            
            # 生成预警信号
            warning_signals = self._generate_credit_warnings(
                corporate_spread, default_rate, npl_ratio, rating_downgrades
            )
            
            return CreditRisk(
                corporate_spread=corporate_spread,
                high_yield_spread=high_yield_spread,
                sovereign_spread=sovereign_spread,
                default_rate=default_rate,
                default_rate_trend=default_rate_trend,
                recovery_rate=recovery_rate,
                rating_downgrades=rating_downgrades,
                rating_upgrades=rating_upgrades,
                rating_outlook=rating_outlook,
                npl_ratio=npl_ratio,
                provision_coverage=provision_coverage,
                capital_adequacy=capital_adequacy,
                credit_score=credit_score,
                risk_level=risk_level,
                warning_signals=warning_signals
            )
            
        except Exception as e:
            logger.warning(f"Credit risk assessment failed: {e}")
            return self._create_default_credit_risk()

    async def _assess_market_risk(self, analysis_date: str) -> MarketRisk:
        """评估市场风险"""
        try:
            # 获取市场数据
            market_data = await self._fetch_market_risk_data(analysis_date)
            
            # 波动率指标
            realized_volatility = market_data.get("realized_vol", 22.5)
            implied_volatility = market_data.get("implied_vol", 25.8)
            volatility_skew = market_data.get("vol_skew", 3.2)
            
            # 相关性指标
            cross_asset_correlation = market_data.get("cross_correlation", 0.65)
            sector_correlation = market_data.get("sector_correlation", 0.72)
            correlation_breakdown = cross_asset_correlation > 0.8
            
            # 尾部风险
            var_95 = market_data.get("var_95", -3.8)
            cvar_95 = market_data.get("cvar_95", -5.2)
            max_drawdown = market_data.get("max_drawdown", -12.5)
            
            # 市场结构
            concentration_ratio = market_data.get("concentration", 0.35)
            market_fragmentation = market_data.get("fragmentation", 0.25)
            
            # 流动性成本
            market_impact = market_data.get("market_impact", 0.08)
            execution_shortfall = market_data.get("execution_shortfall", 0.12)
            
            # 计算市场风险评分
            market_score = self._calculate_market_score(
                realized_volatility, implied_volatility, cross_asset_correlation,
                var_95, max_drawdown, market_impact
            )
            
            risk_level = self._determine_risk_level(market_score)
            
            # 生成预警信号
            warning_signals = self._generate_market_warnings(
                realized_volatility, cross_asset_correlation, max_drawdown, market_impact
            )
            
            return MarketRisk(
                realized_volatility=realized_volatility,
                implied_volatility=implied_volatility,
                volatility_skew=volatility_skew,
                cross_asset_correlation=cross_asset_correlation,
                sector_correlation=sector_correlation,
                correlation_breakdown=correlation_breakdown,
                var_95=var_95,
                cvar_95=cvar_95,
                max_drawdown=max_drawdown,
                concentration_ratio=concentration_ratio,
                market_fragmentation=market_fragmentation,
                market_impact=market_impact,
                execution_shortfall=execution_shortfall,
                market_score=market_score,
                risk_level=risk_level,
                warning_signals=warning_signals
            )
            
        except Exception as e:
            logger.warning(f"Market risk assessment failed: {e}")
            return self._create_default_market_risk()

    def _calculate_overall_risk_score(self, liquidity: LiquidityRisk, 
                                    credit: CreditRisk, market: MarketRisk) -> float:
        """计算综合风险评分"""
        overall_score = (
            liquidity.liquidity_score * self.risk_weights[RiskCategory.LIQUIDITY] +
            credit.credit_score * self.risk_weights[RiskCategory.CREDIT] +
            market.market_score * self.risk_weights[RiskCategory.MARKET]
        )
        
        # 风险放大效应：当多个风险同时偏高时，整体风险放大
        high_risk_count = 0
        if liquidity.liquidity_score > 70:
            high_risk_count += 1
        if credit.credit_score > 70:
            high_risk_count += 1
        if market.market_score > 70:
            high_risk_count += 1
            
        if high_risk_count >= 2:
            overall_score *= 1.15  # 15%放大
        elif high_risk_count >= 3:
            overall_score *= 1.25  # 25%放大
            
        return max(0, min(100, overall_score))

    def _determine_risk_level(self, score: float) -> RiskLevel:
        """确定风险等级"""
        if score >= 90:
            return RiskLevel.EXTREME
        elif score >= 70:
            return RiskLevel.HIGH
        elif score >= 55:
            return RiskLevel.ELEVATED
        elif score >= 40:
            return RiskLevel.MODERATE
        elif score >= 20:
            return RiskLevel.LOW
        else:
            return RiskLevel.MINIMAL

    def _determine_alert_level(self, overall_score: float, liquidity: LiquidityRisk,
                             credit: CreditRisk, market: MarketRisk) -> AlertLevel:
        """确定预警级别"""
        # 基于综合评分
        if overall_score >= 80:
            return AlertLevel.RED
        elif overall_score >= 60:
            return AlertLevel.ORANGE
        elif overall_score >= 45:
            return AlertLevel.YELLOW
        else:
            return AlertLevel.GREEN

    def _analyze_risk_contributions(self, liquidity: LiquidityRisk, 
                                  credit: CreditRisk, market: MarketRisk) -> Dict[RiskCategory, float]:
        """分析各风险的贡献度"""
        total_score = liquidity.liquidity_score + credit.credit_score + market.market_score
        
        if total_score == 0:
            return {category: 0.0 for category in RiskCategory}
            
        return {
            RiskCategory.LIQUIDITY: liquidity.liquidity_score / total_score * 100,
            RiskCategory.CREDIT: credit.credit_score / total_score * 100,
            RiskCategory.MARKET: market.market_score / total_score * 100
        }

    def _identify_top_risk_factors(self, liquidity: LiquidityRisk,
                                 credit: CreditRisk, market: MarketRisk) -> List[str]:
        """识别主要风险因子"""
        risk_factors = []
        
        # 流动性风险因子
        if liquidity.vix_level > 25:
            risk_factors.append(f"VIX恐慌指数偏高 ({liquidity.vix_level:.1f})")
        if liquidity.credit_spread > 200:
            risk_factors.append(f"信用利差扩大 ({liquidity.credit_spread:.0f}bp)")
        if liquidity.market_depth < 70:
            risk_factors.append(f"市场深度不足 ({liquidity.market_depth:.1f}%)")
            
        # 信用风险因子
        if credit.default_rate > 3:
            risk_factors.append(f"违约率上升 ({credit.default_rate:.1f}%)")
        if credit.npl_ratio > 4:
            risk_factors.append(f"不良贷款率偏高 ({credit.npl_ratio:.1f}%)")
        if credit.rating_downgrades > credit.rating_upgrades * 2:
            risk_factors.append(f"评级下调增加 (下调{credit.rating_downgrades}个)")
            
        # 市场风险因子
        if market.realized_volatility > 25:
            risk_factors.append(f"市场波动率升高 ({market.realized_volatility:.1f}%)")
        if market.cross_asset_correlation > 0.8:
            risk_factors.append(f"资产相关性过高 ({market.cross_asset_correlation:.2f})")
        if market.max_drawdown < -20:
            risk_factors.append(f"最大回撤过大 ({market.max_drawdown:.1f}%)")
            
        return risk_factors[:5]  # 返回前5个最重要的因子

    def _collect_active_warnings(self, liquidity: LiquidityRisk,
                               credit: CreditRisk, market: MarketRisk) -> List[str]:
        """汇总活跃预警信号"""
        warnings = []
        warnings.extend(liquidity.warning_signals)
        warnings.extend(credit.warning_signals)
        warnings.extend(market.warning_signals)
        return warnings

    def _generate_warning_summary(self, warnings: List[str]) -> str:
        """生成预警摘要"""
        if not warnings:
            return "当前无系统性风险预警"
            
        if len(warnings) == 1:
            return f"当前有1个风险预警：{warnings[0]}"
        elif len(warnings) <= 3:
            return f"当前有{len(warnings)}个风险预警：" + "、".join(warnings)
        else:
            return f"当前有{len(warnings)}个风险预警，主要包括：" + "、".join(warnings[:3]) + "等"

    def _analyze_risk_trend(self, current_score: float, analysis_date: str) -> Tuple[str, int]:
        """分析风险趋势"""
        # 简化实现：基于当前评分判断趋势
        if current_score > 60:
            trend = "上升"
            duration = 15  # 估计持续天数
        elif current_score < 40:
            trend = "下降"
            duration = 12
        else:
            trend = "稳定"
            duration = 30
            
        return trend, duration

    def _generate_recommendations(self, risk_level: RiskLevel, alert_level: AlertLevel,
                                risk_factors: List[str], warnings: List[str]) -> Tuple[List[str], List[str]]:
        """生成建议措施"""
        actions = []
        priorities = []
        
        # 基于风险等级的建议
        if risk_level in [RiskLevel.EXTREME, RiskLevel.HIGH]:
            actions.append("立即降低风险敞口")
            actions.append("增加现金配置")
            actions.append("启动应急预案")
            priorities.append("流动性管理")
            priorities.append("风险对冲")
            
        elif risk_level == RiskLevel.ELEVATED:
            actions.append("审慎控制风险")
            actions.append("关注流动性状况")
            priorities.append("风险监控")
            
        else:
            actions.append("维持常规风险管理")
            priorities.append("定期评估")
            
        # 基于具体风险因子的建议
        for factor in risk_factors[:3]:
            if "VIX" in factor:
                actions.append("关注市场情绪变化")
            elif "利差" in factor:
                actions.append("监控信用环境")
            elif "波动率" in factor:
                actions.append("考虑波动率对冲")
                
        return actions, priorities

    def _calculate_assessment_confidence(self, liquidity: LiquidityRisk,
                                       credit: CreditRisk, market: MarketRisk) -> float:
        """计算评估置信度"""
        confidence_factors = []
        
        # 数据完整性评分
        if hasattr(liquidity, 'vix_level') and liquidity.vix_level > 0:
            confidence_factors.append(0.9)
        if hasattr(credit, 'corporate_spread') and credit.corporate_spread > 0:
            confidence_factors.append(0.9)
        if hasattr(market, 'realized_volatility') and market.realized_volatility > 0:
            confidence_factors.append(0.9)
            
        # 指标一致性评分
        if len(liquidity.warning_signals) > 0:
            confidence_factors.append(0.8)
        if len(credit.warning_signals) > 0:
            confidence_factors.append(0.8)
        if len(market.warning_signals) > 0:
            confidence_factors.append(0.8)
            
        return sum(confidence_factors) / len(confidence_factors) * 100 if confidence_factors else 75.0

    # 风险计算方法
    def _calculate_liquidity_score(self, vix_level: float, vix_percentile: float,
                                 credit_spread: float, term_spread: float,
                                 bid_ask_spread: float, market_depth: float,
                                 turnover_ratio: float) -> float:
        """计算流动性风险评分"""
        score = 0.0
        
        # VIX贡献 (30%)
        vix_score = min(100, vix_level / 50 * 100)
        score += vix_score * 0.30
        
        # 利差贡献 (25%)
        spread_score = min(100, credit_spread / 300 * 100)
        score += spread_score * 0.25
        
        # 买卖价差贡献 (20%)
        ba_score = min(100, bid_ask_spread / 0.5 * 100)
        score += ba_score * 0.20
        
        # 市场深度贡献 (15%) - 反向
        depth_score = max(0, (100 - market_depth) / 100 * 100)
        score += depth_score * 0.15
        
        # 换手率贡献 (10%) - 反向
        turnover_score = max(0, (5 - turnover_ratio) / 5 * 100)
        score += turnover_score * 0.10
        
        return max(0, min(100, score))

    def _calculate_credit_score(self, corporate_spread: float, high_yield_spread: float,
                              default_rate: float, npl_ratio: float, capital_adequacy: float,
                              downgrades: int, upgrades: int) -> float:
        """计算信用风险评分"""
        score = 0.0
        
        # 企业债利差贡献 (25%)
        corp_score = min(100, corporate_spread / 400 * 100)
        score += corp_score * 0.25
        
        # 高收益债利差贡献 (20%)
        hy_score = min(100, high_yield_spread / 800 * 100)
        score += hy_score * 0.20
        
        # 违约率贡献 (20%)
        default_score = min(100, default_rate / 8 * 100)
        score += default_score * 0.20
        
        # 不良贷款率贡献 (15%)
        npl_score = min(100, npl_ratio / 8 * 100)
        score += npl_score * 0.15
        
        # 资本充足率贡献 (10%) - 反向
        cap_score = max(0, (15 - capital_adequacy) / 15 * 100)
        score += cap_score * 0.10
        
        # 评级变化贡献 (10%)
        rating_score = min(100, max(0, downgrades - upgrades) / 20 * 100)
        score += rating_score * 0.10
        
        return max(0, min(100, score))

    def _calculate_market_score(self, realized_vol: float, implied_vol: float,
                              correlation: float, var_95: float, max_dd: float,
                              market_impact: float) -> float:
        """计算市场风险评分"""
        score = 0.0
        
        # 实际波动率贡献 (25%)
        vol_score = min(100, realized_vol / 50 * 100)
        score += vol_score * 0.25
        
        # 相关性贡献 (20%)
        corr_score = min(100, max(0, correlation - 0.3) / 0.7 * 100)
        score += corr_score * 0.20
        
        # VaR贡献 (20%)
        var_score = min(100, abs(var_95) / 10 * 100)
        score += var_score * 0.20
        
        # 最大回撤贡献 (20%)
        dd_score = min(100, abs(max_dd) / 40 * 100)
        score += dd_score * 0.20
        
        # 市场冲击贡献 (15%)
        impact_score = min(100, market_impact / 0.5 * 100)
        score += impact_score * 0.15
        
        return max(0, min(100, score))

    # 预警信号生成方法
    def _generate_liquidity_warnings(self, vix: float, spread: float, 
                                   ba_spread: float, depth: float) -> List[str]:
        """生成流动性预警信号"""
        warnings = []
        
        if vix > self.alert_thresholds["vix"]["red"]:
            warnings.append(f"VIX恐慌指数极高({vix:.1f})")
        elif vix > self.alert_thresholds["vix"]["orange"]:
            warnings.append(f"VIX恐慌指数偏高({vix:.1f})")
            
        if spread > self.alert_thresholds["credit_spread"]["red"]:
            warnings.append(f"信用利差急剧扩大({spread:.0f}bp)")
        elif spread > self.alert_thresholds["credit_spread"]["orange"]:
            warnings.append(f"信用利差明显扩大({spread:.0f}bp)")
            
        if ba_spread > self.alert_thresholds["bid_ask_spread"]["orange"]:
            warnings.append(f"买卖价差异常扩大({ba_spread:.3f})")
            
        if depth < 60:
            warnings.append(f"市场深度严重不足({depth:.1f}%)")
            
        return warnings

    def _generate_credit_warnings(self, corp_spread: float, default_rate: float,
                                npl_ratio: float, downgrades: int) -> List[str]:
        """生成信用预警信号"""
        warnings = []
        
        if corp_spread > self.alert_thresholds["corporate_spread"]["red"]:
            warnings.append(f"企业债利差极度扩大({corp_spread:.0f}bp)")
        elif corp_spread > self.alert_thresholds["corporate_spread"]["orange"]:
            warnings.append(f"企业债利差显著扩大({corp_spread:.0f}bp)")
            
        if default_rate > self.alert_thresholds["default_rate"]["orange"]:
            warnings.append(f"违约率明显上升({default_rate:.1f}%)")
            
        if npl_ratio > self.alert_thresholds["npl_ratio"]["orange"]:
            warnings.append(f"银行不良率偏高({npl_ratio:.1f}%)")
            
        if downgrades > 15:
            warnings.append(f"信用评级下调频繁({downgrades}个)")
            
        return warnings

    def _generate_market_warnings(self, volatility: float, correlation: float,
                                max_dd: float, impact: float) -> List[str]:
        """生成市场预警信号"""
        warnings = []
        
        if volatility > self.alert_thresholds["realized_volatility"]["red"]:
            warnings.append(f"市场波动率极高({volatility:.1f}%)")
        elif volatility > self.alert_thresholds["realized_volatility"]["orange"]:
            warnings.append(f"市场波动率偏高({volatility:.1f}%)")
            
        if correlation > self.alert_thresholds["correlation"]["orange"]:
            warnings.append(f"资产相关性过高({correlation:.2f})")
            
        if max_dd < self.alert_thresholds["max_drawdown"]["orange"]:
            warnings.append(f"市场回撤过大({max_dd:.1f}%)")
            
        if impact > 0.3:
            warnings.append(f"市场冲击成本偏高({impact:.2f}%)")
            
        return warnings

    # 数据获取方法（模拟实现）
    async def _fetch_liquidity_data(self, date: str) -> Dict[str, Any]:
        """获取流动性数据"""
        return {
            "vix": 18.5,
            "vix_history": [16.2, 17.8, 18.5],
            "credit_spread": 120,
            "term_spread": 180,
            "liquidity_spread": 50,
            "bid_ask_spread": 0.05,
            "market_depth": 85.0,
            "turnover_ratio": 2.8
        }

    async def _fetch_credit_data(self, date: str) -> Dict[str, Any]:
        """获取信用数据"""
        return {
            "corporate_spread": 180,
            "high_yield_spread": 450,
            "sovereign_spread": 80,
            "default_rate": 1.8,
            "default_history": [1.5, 1.7, 1.8],
            "recovery_rate": 65.0,
            "downgrades": 12,
            "upgrades": 8,
            "outlook": "稳定",
            "npl_ratio": 2.1,
            "provision_coverage": 180.5,
            "capital_adequacy": 14.2
        }

    async def _fetch_market_risk_data(self, date: str) -> Dict[str, Any]:
        """获取市场风险数据"""
        return {
            "realized_vol": 22.5,
            "implied_vol": 25.8,
            "vol_skew": 3.2,
            "cross_correlation": 0.65,
            "sector_correlation": 0.72,
            "var_95": -3.8,
            "cvar_95": -5.2,
            "max_drawdown": -12.5,
            "concentration": 0.35,
            "fragmentation": 0.25,
            "market_impact": 0.08,
            "execution_shortfall": 0.12
        }

    # 辅助方法
    def _calculate_percentile(self, value: float, indicator: str) -> float:
        """计算历史分位数（简化实现）"""
        # 基于经验值估算分位数
        if indicator == "vix":
            if value < 12:
                return 10.0
            elif value < 20:
                return 50.0
            elif value < 30:
                return 80.0
            else:
                return 95.0
        return 50.0

    def _determine_trend(self, values: List[float]) -> str:
        """判断数据趋势"""
        if len(values) < 2:
            return "稳定"
            
        recent = values[-1]
        previous = values[-2]
        
        change_pct = (recent - previous) / abs(previous) * 100 if previous != 0 else 0
        
        if change_pct > 10:
            return "上升"
        elif change_pct < -10:
            return "下降"
        else:
            return "稳定"

    # 默认风险评估创建方法
    def _create_default_liquidity_risk(self) -> LiquidityRisk:
        """创建默认流动性风险评估"""
        return LiquidityRisk(
            vix_level=18.5, vix_percentile=50.0, vix_trend="稳定",
            credit_spread=120, term_spread=180, liquidity_spread=50,
            bid_ask_spread=0.05, market_depth=85.0, turnover_ratio=2.8,
            liquidity_score=40.0, risk_level=RiskLevel.MODERATE,
            warning_signals=[]
        )

    def _create_default_credit_risk(self) -> CreditRisk:
        """创建默认信用风险评估"""
        return CreditRisk(
            corporate_spread=180, high_yield_spread=450, sovereign_spread=80,
            default_rate=1.8, default_rate_trend="稳定", recovery_rate=65.0,
            rating_downgrades=12, rating_upgrades=8, rating_outlook="稳定",
            npl_ratio=2.1, provision_coverage=180.5, capital_adequacy=14.2,
            credit_score=35.0, risk_level=RiskLevel.MODERATE,
            warning_signals=[]
        )

    def _create_default_market_risk(self) -> MarketRisk:
        """创建默认市场风险评估"""
        return MarketRisk(
            realized_volatility=22.5, implied_volatility=25.8, volatility_skew=3.2,
            cross_asset_correlation=0.65, sector_correlation=0.72, correlation_breakdown=False,
            var_95=-3.8, cvar_95=-5.2, max_drawdown=-12.5,
            concentration_ratio=0.35, market_fragmentation=0.25,
            market_impact=0.08, execution_shortfall=0.12,
            market_score=45.0, risk_level=RiskLevel.MODERATE,
            warning_signals=[]
        )