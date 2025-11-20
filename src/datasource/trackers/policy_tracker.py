"""
政策跟踪系统 - Policy Tracking System
实时跟踪和评估货币政策、财政政策、监管政策对市场的影响

主要功能:
1. 货币政策追踪 (利率、货币供应量、汇率政策)
2. 财政政策监控 (税收政策、政府支出、债务水平)
3. 监管政策分析 (行业监管、金融监管、环保政策)
4. 政策影响量化评估
5. 政策预期管理
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from enum import Enum
import logging
import re

from ..manager import DataSourceManager, get_manager
from ..models.base import DataResponse

logger = logging.getLogger(__name__)

class PolicyType(Enum):
    """政策类型枚举"""
    MONETARY = "货币政策"
    FISCAL = "财政政策"
    REGULATORY = "监管政策"
    TRADE = "贸易政策"
    ENVIRONMENTAL = "环保政策"

class PolicyImpact(Enum):
    """政策影响程度"""
    VERY_POSITIVE = "极度利好"  # 90-100
    POSITIVE = "利好"          # 70-89
    SLIGHT_POSITIVE = "偏利好" # 55-69
    NEUTRAL = "中性"           # 45-54
    SLIGHT_NEGATIVE = "偏利空" # 30-44
    NEGATIVE = "利空"          # 10-29
    VERY_NEGATIVE = "极度利空" # 0-9

@dataclass
class PolicyEvent:
    """政策事件数据结构"""
    event_id: str
    policy_type: PolicyType
    title: str
    description: str
    announcement_date: datetime
    effective_date: Optional[datetime] = None
    
    # 影响评估
    market_impact_score: float = 50.0  # 0-100
    sector_impacts: Dict[str, float] = None  # 行业影响
    duration_estimate: int = 30  # 预计影响天数
    
    # 政策强度
    policy_strength: str = "中等"  # 强、中等、弱
    implementation_certainty: float = 0.8  # 实施确定性
    
    # 元数据
    source: str = "官方发布"
    confidence: float = 0.9
    keywords: List[str] = None

@dataclass
class MonetaryPolicy:
    """货币政策状态"""
    policy_rate: float  # 基准利率
    rate_trend: str     # 利率趋势: "上升", "下降", "稳定"
    rate_cycle_stage: str  # 利率周期: "紧缩", "宽松", "中性"
    
    money_supply_m2_growth: float  # M2增长率
    reserve_ratio: float           # 存款准备金率
    
    policy_stance: str    # 政策立场: "鹰派", "鸽派", "中性"
    policy_tools: List[str]  # 使用的政策工具
    
    last_update: datetime
    next_meeting_date: Optional[datetime] = None

@dataclass
class FiscalPolicy:
    """财政政策状态"""
    deficit_ratio: float      # 赤字率
    debt_to_gdp: float       # 债务率
    fiscal_stance: str       # 财政立场: "积极", "稳健", "紧缩"
    
    tax_policy_direction: str     # 税收政策方向
    spending_policy_direction: str  # 支出政策方向
    
    infrastructure_investment: float  # 基建投资增速
    social_spending: float           # 民生支出增速
    
    last_update: datetime

@dataclass
class RegulatoryEnvironment:
    """监管环境评估"""
    overall_tone: str  # 整体基调: "严监管", "适度监管", "宽松监管"
    
    financial_regulation: float    # 金融监管强度 0-100
    industry_regulation: float     # 行业监管强度 0-100
    environmental_regulation: float # 环保监管强度 0-100
    
    recent_policies: List[PolicyEvent]
    regulatory_trend: str  # 监管趋势: "收紧", "放松", "稳定"
    
    sector_regulatory_scores: Dict[str, float]  # 各行业监管评分
    
    last_update: datetime

@dataclass
class PolicyAssessment:
    """综合政策评估结果"""
    overall_score: float  # 综合政策评分 0-100
    policy_impact: PolicyImpact
    
    monetary_score: float
    fiscal_score: float  
    regulatory_score: float
    
    # 时间维度分析
    short_term_impact: float   # 1个月影响
    medium_term_impact: float  # 3个月影响
    long_term_impact: float    # 12个月影响
    
    # 风险因素
    policy_risks: List[str]
    policy_opportunities: List[str]
    
    # 行业影响
    sector_impacts: Dict[str, float]
    
    confidence_level: float
    assessment_date: datetime

class PolicyTracker:
    """政策跟踪分析器"""
    
    def __init__(self, manager: Optional[DataSourceManager] = None):
        self.manager = manager or get_manager()
        
        # 政策权重配置
        self.policy_weights = {
            PolicyType.MONETARY: 0.35,     # 货币政策权重最高
            PolicyType.FISCAL: 0.30,       # 财政政策次之
            PolicyType.REGULATORY: 0.25,   # 监管政策
            PolicyType.TRADE: 0.10         # 贸易政策
        }
        
        # 行业敏感度矩阵
        self.sector_sensitivity = {
            "银行": {"MONETARY": 0.9, "FISCAL": 0.3, "REGULATORY": 0.8},
            "房地产": {"MONETARY": 0.8, "FISCAL": 0.6, "REGULATORY": 0.7},
            "基建": {"FISCAL": 0.9, "MONETARY": 0.4, "REGULATORY": 0.5},
            "科技": {"REGULATORY": 0.6, "TRADE": 0.8, "FISCAL": 0.4},
            "消费": {"FISCAL": 0.7, "MONETARY": 0.5, "REGULATORY": 0.3},
            "医药": {"REGULATORY": 0.9, "FISCAL": 0.5, "TRADE": 0.3},
            "能源": {"REGULATORY": 0.8, "ENVIRONMENTAL": 0.9, "TRADE": 0.6},
            "制造业": {"TRADE": 0.7, "ENVIRONMENTAL": 0.6, "FISCAL": 0.5}
        }
        
        # 政策关键词库
        self.policy_keywords = {
            PolicyType.MONETARY: {
                "利好": ["降准", "降息", "流动性投放", "货币宽松", "定向降准"],
                "利空": ["加息", "提准", "流动性回笼", "货币紧缩", "去杠杆"],
                "中性": ["MLF", "逆回购", "结构性工具", "政策利率", "汇率稳定"]
            },
            PolicyType.FISCAL: {
                "利好": ["减税", "降费", "专项债", "积极财政", "基建投资", "消费刺激"],
                "利空": ["加税", "财政收缩", "债务控制", "支出削减"],
                "中性": ["稳健财政", "结构性减税", "财政平衡", "预算管理"]
            },
            PolicyType.REGULATORY: {
                "利好": ["监管放松", "政策支持", "准入放宽", "鼓励发展"],
                "利空": ["强监管", "限制措施", "准入收紧", "处罚加强"],
                "中性": ["规范发展", "合规要求", "行业指导", "标准制定"]
            }
        }

    async def track_policy_environment(self, 
                                     analysis_date: Optional[str] = None,
                                     sectors: Optional[List[str]] = None) -> PolicyAssessment:
        """
        跟踪和评估政策环境
        
        Args:
            analysis_date: 分析日期
            sectors: 关注的行业列表
            
        Returns:
            PolicyAssessment: 政策环境评估结果
        """
        if not analysis_date:
            analysis_date = datetime.now().strftime('%Y-%m-%d')
            
        if not sectors:
            sectors = ["银行", "房地产", "科技", "消费", "制造业"]
            
        logger.info(f"Starting policy environment tracking for {analysis_date}")
        
        try:
            # 并行获取各类政策数据
            tasks = [
                self._analyze_monetary_policy(analysis_date),
                self._analyze_fiscal_policy(analysis_date),
                self._analyze_regulatory_environment(analysis_date),
                self._collect_recent_policy_events(analysis_date)
            ]
            
            monetary_policy, fiscal_policy, regulatory_env, policy_events = await asyncio.gather(*tasks)
            
            # 计算各政策模块评分
            monetary_score = self._calculate_monetary_score(monetary_policy)
            fiscal_score = self._calculate_fiscal_score(fiscal_policy)
            regulatory_score = self._calculate_regulatory_score(regulatory_env)
            
            # 综合政策评分
            overall_score = (
                monetary_score * self.policy_weights[PolicyType.MONETARY] +
                fiscal_score * self.policy_weights[PolicyType.FISCAL] +
                regulatory_score * self.policy_weights[PolicyType.REGULATORY]
            )
            
            # 政策影响等级
            policy_impact = self._determine_policy_impact(overall_score)
            
            # 时间维度影响分析
            short_term, medium_term, long_term = self._analyze_temporal_impact(
                monetary_policy, fiscal_policy, regulatory_env, policy_events
            )
            
            # 风险机会分析
            risks, opportunities = self._analyze_policy_risks_opportunities(
                monetary_policy, fiscal_policy, regulatory_env, policy_events
            )
            
            # 行业影响分析
            sector_impacts = self._analyze_sector_impacts(
                sectors, monetary_score, fiscal_score, regulatory_score, policy_events
            )
            
            # 置信度评估
            confidence = self._calculate_confidence(monetary_policy, fiscal_policy, regulatory_env)
            
            assessment = PolicyAssessment(
                overall_score=overall_score,
                policy_impact=policy_impact,
                monetary_score=monetary_score,
                fiscal_score=fiscal_score,
                regulatory_score=regulatory_score,
                short_term_impact=short_term,
                medium_term_impact=medium_term,
                long_term_impact=long_term,
                policy_risks=risks,
                policy_opportunities=opportunities,
                sector_impacts=sector_impacts,
                confidence_level=confidence,
                assessment_date=datetime.strptime(analysis_date, '%Y-%m-%d')
            )
            
            logger.info(f"Policy assessment completed: overall_score={overall_score:.1f}, impact={policy_impact.value}")
            return assessment
            
        except Exception as e:
            logger.error(f"Policy tracking failed: {e}")
            raise

    async def _analyze_monetary_policy(self, analysis_date: str) -> MonetaryPolicy:
        """分析货币政策状况"""
        try:
            # 获取货币政策数据
            policy_data = await self._fetch_monetary_data(analysis_date)
            
            # 分析利率趋势
            rate_trend, rate_cycle = self._analyze_interest_rate_trend(policy_data.get("rates", []))
            
            # 分析货币供应量
            m2_growth = self._analyze_money_supply(policy_data.get("money_supply", []))
            
            # 判断政策立场
            stance = self._determine_monetary_stance(rate_trend, m2_growth, policy_data)
            
            # 识别政策工具
            tools = self._identify_policy_tools(policy_data)
            
            return MonetaryPolicy(
                policy_rate=policy_data.get("policy_rate", 4.35),
                rate_trend=rate_trend,
                rate_cycle_stage=rate_cycle,
                money_supply_m2_growth=m2_growth,
                reserve_ratio=policy_data.get("reserve_ratio", 11.5),
                policy_stance=stance,
                policy_tools=tools,
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d'),
                next_meeting_date=self._get_next_policy_meeting()
            )
            
        except Exception as e:
            logger.warning(f"Monetary policy analysis failed: {e}")
            # 返回默认值
            return MonetaryPolicy(
                policy_rate=4.35,
                rate_trend="稳定",
                rate_cycle_stage="中性",
                money_supply_m2_growth=10.5,
                reserve_ratio=11.5,
                policy_stance="中性",
                policy_tools=["公开市场操作"],
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )

    async def _analyze_fiscal_policy(self, analysis_date: str) -> FiscalPolicy:
        """分析财政政策状况"""
        try:
            fiscal_data = await self._fetch_fiscal_data(analysis_date)
            
            # 分析财政立场
            stance = self._determine_fiscal_stance(fiscal_data)
            
            # 分析税收和支出政策方向
            tax_direction = self._analyze_tax_policy(fiscal_data.get("tax_policies", []))
            spending_direction = self._analyze_spending_policy(fiscal_data.get("spending_policies", []))
            
            return FiscalPolicy(
                deficit_ratio=fiscal_data.get("deficit_ratio", 3.0),
                debt_to_gdp=fiscal_data.get("debt_ratio", 50.2),
                fiscal_stance=stance,
                tax_policy_direction=tax_direction,
                spending_policy_direction=spending_direction,
                infrastructure_investment=fiscal_data.get("infra_investment", 8.5),
                social_spending=fiscal_data.get("social_spending", 6.2),
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )
            
        except Exception as e:
            logger.warning(f"Fiscal policy analysis failed: {e}")
            return FiscalPolicy(
                deficit_ratio=3.0,
                debt_to_gdp=50.0,
                fiscal_stance="稳健",
                tax_policy_direction="结构性减税",
                spending_policy_direction="民生导向",
                infrastructure_investment=8.0,
                social_spending=6.0,
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )

    async def _analyze_regulatory_environment(self, analysis_date: str) -> RegulatoryEnvironment:
        """分析监管环境"""
        try:
            regulatory_data = await self._fetch_regulatory_data(analysis_date)
            
            # 评估整体监管基调
            overall_tone = self._assess_regulatory_tone(regulatory_data)
            
            # 计算各领域监管强度
            financial_intensity = self._calculate_financial_regulation_intensity(regulatory_data)
            industry_intensity = self._calculate_industry_regulation_intensity(regulatory_data)
            environmental_intensity = self._calculate_environmental_regulation_intensity(regulatory_data)
            
            # 分析监管趋势
            trend = self._analyze_regulatory_trend(regulatory_data)
            
            # 各行业监管评分
            sector_scores = self._calculate_sector_regulatory_scores(regulatory_data)
            
            return RegulatoryEnvironment(
                overall_tone=overall_tone,
                financial_regulation=financial_intensity,
                industry_regulation=industry_intensity,
                environmental_regulation=environmental_intensity,
                recent_policies=[],  # 将在后续填充
                regulatory_trend=trend,
                sector_regulatory_scores=sector_scores,
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )
            
        except Exception as e:
            logger.warning(f"Regulatory environment analysis failed: {e}")
            return RegulatoryEnvironment(
                overall_tone="适度监管",
                financial_regulation=60.0,
                industry_regulation=55.0,
                environmental_regulation=70.0,
                recent_policies=[],
                regulatory_trend="稳定",
                sector_regulatory_scores={"银行": 65, "房地产": 70, "科技": 50},
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )

    async def _collect_recent_policy_events(self, analysis_date: str, days_back: int = 30) -> List[PolicyEvent]:
        """收集近期政策事件"""
        try:
            events_data = await self._fetch_policy_events(analysis_date, days_back)
            
            events = []
            for event_data in events_data:
                event = self._parse_policy_event(event_data)
                if event:
                    events.append(event)
                    
            return events
            
        except Exception as e:
            logger.warning(f"Policy events collection failed: {e}")
            return []

    def _calculate_monetary_score(self, policy: MonetaryPolicy) -> float:
        """计算货币政策评分"""
        score = 50.0  # 基准分
        
        # 利率周期评分
        cycle_scores = {"宽松": 75, "中性": 50, "紧缩": 25}
        score += (cycle_scores.get(policy.rate_cycle_stage, 50) - 50) * 0.4
        
        # 政策立场评分
        stance_scores = {"鸽派": 70, "中性": 50, "鹰派": 30}
        score += (stance_scores.get(policy.policy_stance, 50) - 50) * 0.3
        
        # M2增长率评分（适度增长为佳）
        if 8 <= policy.money_supply_m2_growth <= 12:
            score += 10
        elif policy.money_supply_m2_growth > 15:
            score += 5  # 过度宽松
        elif policy.money_supply_m2_growth < 5:
            score -= 10  # 过度紧缩
        
        # 政策工具多样性
        if len(policy.policy_tools) > 2:
            score += 5
            
        return max(0, min(100, score))

    def _calculate_fiscal_score(self, policy: FiscalPolicy) -> float:
        """计算财政政策评分"""
        score = 50.0
        
        # 财政立场评分
        stance_scores = {"积极": 70, "稳健": 50, "紧缩": 30}
        score += (stance_scores.get(policy.fiscal_stance, 50) - 50) * 0.4
        
        # 债务可持续性评分
        if policy.debt_to_gdp < 60:  # 国际警戒线
            score += 10
        elif policy.debt_to_gdp > 80:
            score -= 15
            
        # 赤字率适度性
        if policy.deficit_ratio <= 3:  # 国际标准
            score += 5
        elif policy.deficit_ratio > 5:
            score -= 10
            
        # 基建投资增速
        if policy.infrastructure_investment > 5:
            score += 8
            
        return max(0, min(100, score))

    def _calculate_regulatory_score(self, env: RegulatoryEnvironment) -> float:
        """计算监管环境评分"""
        score = 50.0
        
        # 监管基调评分
        tone_scores = {"宽松监管": 70, "适度监管": 50, "严监管": 30}
        score += (tone_scores.get(env.overall_tone, 50) - 50) * 0.3
        
        # 监管趋势评分
        trend_scores = {"放松": 70, "稳定": 50, "收紧": 30}
        score += (trend_scores.get(env.regulatory_trend, 50) - 50) * 0.3
        
        # 监管强度适度性（过强过弱都不好）
        avg_intensity = (env.financial_regulation + env.industry_regulation + env.environmental_regulation) / 3
        if 40 <= avg_intensity <= 70:
            score += 10
        elif avg_intensity > 80:
            score -= 15
            
        return max(0, min(100, score))

    def _determine_policy_impact(self, score: float) -> PolicyImpact:
        """确定政策影响等级"""
        if score >= 90:
            return PolicyImpact.VERY_POSITIVE
        elif score >= 70:
            return PolicyImpact.POSITIVE
        elif score >= 55:
            return PolicyImpact.SLIGHT_POSITIVE
        elif score >= 45:
            return PolicyImpact.NEUTRAL
        elif score >= 30:
            return PolicyImpact.SLIGHT_NEGATIVE
        elif score >= 10:
            return PolicyImpact.NEGATIVE
        else:
            return PolicyImpact.VERY_NEGATIVE

    def _analyze_temporal_impact(self, monetary: MonetaryPolicy, fiscal: FiscalPolicy, 
                               regulatory: RegulatoryEnvironment, events: List[PolicyEvent]) -> Tuple[float, float, float]:
        """分析时间维度影响"""
        # 短期影响（1个月）- 主要看货币政策和近期事件
        short_term = (self._calculate_monetary_score(monetary) * 0.6 + 
                     sum(e.market_impact_score for e in events if e.duration_estimate <= 30) / max(1, len(events)) * 0.4)
        
        # 中期影响（3个月）- 综合三类政策
        medium_term = (self._calculate_monetary_score(monetary) * 0.4 +
                      self._calculate_fiscal_score(fiscal) * 0.4 +
                      self._calculate_regulatory_score(regulatory) * 0.2)
        
        # 长期影响（12个月）- 重点看财政和监管
        long_term = (self._calculate_fiscal_score(fiscal) * 0.5 +
                    self._calculate_regulatory_score(regulatory) * 0.3 +
                    self._calculate_monetary_score(monetary) * 0.2)
        
        return short_term, medium_term, long_term

    def _analyze_policy_risks_opportunities(self, monetary: MonetaryPolicy, fiscal: FiscalPolicy,
                                          regulatory: RegulatoryEnvironment, events: List[PolicyEvent]) -> Tuple[List[str], List[str]]:
        """分析政策风险和机会"""
        risks = []
        opportunities = []
        
        # 货币政策风险机会
        if monetary.policy_stance == "鹰派":
            risks.append("货币政策收紧压制流动性")
        elif monetary.policy_stance == "鸽派":
            opportunities.append("货币宽松提供流动性支持")
            
        # 财政政策风险机会  
        if fiscal.fiscal_stance == "积极":
            opportunities.append("积极财政刺激经济增长")
        elif fiscal.debt_to_gdp > 70:
            risks.append("政府债务水平偏高")
            
        # 监管政策风险机会
        if regulatory.overall_tone == "严监管":
            risks.append("监管趋严影响市场情绪")
        elif regulatory.regulatory_trend == "放松":
            opportunities.append("监管放松释放制度红利")
            
        return risks, opportunities

    def _analyze_sector_impacts(self, sectors: List[str], monetary_score: float, fiscal_score: float,
                               regulatory_score: float, events: List[PolicyEvent]) -> Dict[str, float]:
        """分析各行业政策影响"""
        sector_impacts = {}
        
        for sector in sectors:
            if sector not in self.sector_sensitivity:
                sector_impacts[sector] = 50.0
                continue
                
            sensitivity = self.sector_sensitivity[sector]
            impact = 50.0
            
            # 根据敏感度加权计算
            if "MONETARY" in sensitivity:
                impact += (monetary_score - 50) * sensitivity["MONETARY"] * 0.35
            if "FISCAL" in sensitivity:
                impact += (fiscal_score - 50) * sensitivity["FISCAL"] * 0.30
            if "REGULATORY" in sensitivity:
                impact += (regulatory_score - 50) * sensitivity["REGULATORY"] * 0.25
                
            # 特定事件影响
            for event in events:
                if sector in event.sector_impacts:
                    impact += (event.sector_impacts[sector] - 50) * 0.1
                    
            sector_impacts[sector] = max(0, min(100, impact))
            
        return sector_impacts

    def _calculate_confidence(self, monetary: MonetaryPolicy, fiscal: FiscalPolicy, regulatory: RegulatoryEnvironment) -> float:
        """计算评估置信度"""
        confidence_factors = []
        
        # 数据时效性
        now = datetime.now()
        monetary_age = (now - monetary.last_update).days
        fiscal_age = (now - fiscal.last_update).days
        regulatory_age = (now - regulatory.last_update).days
        
        # 数据新鲜度评分
        for age in [monetary_age, fiscal_age, regulatory_age]:
            if age <= 7:
                confidence_factors.append(0.9)
            elif age <= 30:
                confidence_factors.append(0.8)
            else:
                confidence_factors.append(0.6)
                
        # 政策工具多样性
        tool_diversity = len(monetary.policy_tools) / 5  # 最多5种工具
        confidence_factors.append(min(1.0, tool_diversity))
        
        return sum(confidence_factors) / len(confidence_factors) * 100

    # 数据获取模拟方法
    async def _fetch_monetary_data(self, date: str) -> Dict:
        """获取货币政策数据"""
        return {
            "policy_rate": 4.35,
            "reserve_ratio": 11.5,
            "rates": [
                {"date": date, "rate": 4.35},
                {"date": (datetime.strptime(date, '%Y-%m-%d') - timedelta(days=30)).strftime('%Y-%m-%d'), "rate": 4.35}
            ],
            "money_supply": [{"date": date, "m2_growth": 10.5}],
            "tools": ["MLF", "逆回购", "定向降准"]
        }

    async def _fetch_fiscal_data(self, date: str) -> Dict:
        """获取财政政策数据"""
        return {
            "deficit_ratio": 3.0,
            "debt_ratio": 50.2,
            "infra_investment": 8.5,
            "social_spending": 6.2,
            "tax_policies": [{"type": "减税", "impact": 70}],
            "spending_policies": [{"type": "基建", "impact": 65}]
        }

    async def _fetch_regulatory_data(self, date: str) -> Dict:
        """获取监管政策数据"""
        return {
            "financial_reg": {"intensity": 60, "trend": "稳定"},
            "industry_reg": {"intensity": 55, "trend": "放松"},
            "env_reg": {"intensity": 70, "trend": "加强"},
            "overall_tone": "适度监管"
        }

    async def _fetch_policy_events(self, date: str, days_back: int) -> List[Dict]:
        """获取政策事件数据"""
        return [
            {
                "title": "央行开展MLF操作",
                "type": "MONETARY",
                "date": date,
                "impact": 55,
                "description": "央行开展中期借贷便利操作2000亿元"
            }
        ]

    # 辅助分析方法
    def _analyze_interest_rate_trend(self, rate_data: List[Dict]) -> Tuple[str, str]:
        """分析利率趋势"""
        if len(rate_data) < 2:
            return "稳定", "中性"
            
        current = rate_data[0]["rate"]
        previous = rate_data[1]["rate"]
        
        if current > previous + 0.1:
            return "上升", "紧缩"
        elif current < previous - 0.1:
            return "下降", "宽松"
        else:
            return "稳定", "中性"

    def _analyze_money_supply(self, m2_data: List[Dict]) -> float:
        """分析货币供应量增长"""
        if not m2_data:
            return 10.0
        return m2_data[0]["m2_growth"]

    def _determine_monetary_stance(self, rate_trend: str, m2_growth: float, data: Dict) -> str:
        """确定货币政策立场"""
        if rate_trend == "下降" or m2_growth > 12:
            return "鸽派"
        elif rate_trend == "上升" or m2_growth < 8:
            return "鹰派"
        else:
            return "中性"

    def _identify_policy_tools(self, data: Dict) -> List[str]:
        """识别政策工具"""
        return data.get("tools", ["公开市场操作"])

    def _get_next_policy_meeting(self) -> Optional[datetime]:
        """获取下次政策会议时间"""
        # 模拟：假设每季度有政策会议
        now = datetime.now()
        next_quarter = ((now.month - 1) // 3 + 1) * 3 + 1
        if next_quarter > 12:
            next_quarter = 1
            year = now.year + 1
        else:
            year = now.year
        return datetime(year, next_quarter, 15)

    def _determine_fiscal_stance(self, data: Dict) -> str:
        """确定财政政策立场"""
        deficit = data.get("deficit_ratio", 3.0)
        if deficit > 3.5:
            return "积极"
        elif deficit < 2.0:
            return "紧缩"
        else:
            return "稳健"

    def _analyze_tax_policy(self, tax_policies: List[Dict]) -> str:
        """分析税收政策方向"""
        if not tax_policies:
            return "稳定"
        
        total_impact = sum(p.get("impact", 50) for p in tax_policies)
        avg_impact = total_impact / len(tax_policies)
        
        if avg_impact > 60:
            return "减税导向"
        elif avg_impact < 40:
            return "增收导向"
        else:
            return "结构调整"

    def _analyze_spending_policy(self, spending_policies: List[Dict]) -> str:
        """分析支出政策方向"""
        if not spending_policies:
            return "稳定"
        return "基建导向"  # 简化实现

    def _assess_regulatory_tone(self, data: Dict) -> str:
        """评估监管整体基调"""
        return data.get("overall_tone", "适度监管")

    def _calculate_financial_regulation_intensity(self, data: Dict) -> float:
        """计算金融监管强度"""
        return data.get("financial_reg", {}).get("intensity", 60.0)

    def _calculate_industry_regulation_intensity(self, data: Dict) -> float:
        """计算行业监管强度"""
        return data.get("industry_reg", {}).get("intensity", 55.0)

    def _calculate_environmental_regulation_intensity(self, data: Dict) -> float:
        """计算环保监管强度"""
        return data.get("env_reg", {}).get("intensity", 70.0)

    def _analyze_regulatory_trend(self, data: Dict) -> str:
        """分析监管趋势"""
        return "稳定"  # 简化实现

    def _calculate_sector_regulatory_scores(self, data: Dict) -> Dict[str, float]:
        """计算各行业监管评分"""
        return {"银行": 65, "房地产": 70, "科技": 50, "制造业": 55}

    def _parse_policy_event(self, event_data: Dict) -> Optional[PolicyEvent]:
        """解析政策事件"""
        try:
            return PolicyEvent(
                event_id=f"policy_{event_data['date']}_{hash(event_data['title']) % 10000}",
                policy_type=PolicyType(event_data.get("type", "MONETARY")),
                title=event_data["title"],
                description=event_data.get("description", ""),
                announcement_date=datetime.strptime(event_data["date"], '%Y-%m-%d'),
                market_impact_score=event_data.get("impact", 50),
                source="政策追踪系统"
            )
        except Exception as e:
            logger.warning(f"Failed to parse policy event: {e}")
            return None