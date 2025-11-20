"""
国际对比分析框架 - International Market Comparison Framework
提供A股市场与全球主要市场的多维度对比分析

主要功能:
1. 市场表现对比 (涨跌幅、波动率、估值水平)
2. 资金流向分析 (外资流入、本土资金配置)
3. 政策环境对比 (货币政策、财政政策差异)
4. 经济基本面对比 (GDP增速、通胀水平、就业状况)
5. 行业配置优势分析
6. 相对投资价值评估
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Union
from dataclasses import dataclass
from enum import Enum
import logging

from ..manager import DataSourceManager, get_manager
from ..models.base import DataResponse
from ..calculators.technical_indicators import TechnicalIndicators

logger = logging.getLogger(__name__)

class MarketRegion(Enum):
    """市场区域枚举"""
    CHINA_A = "中国A股"
    US = "美国市场"
    EUROPE = "欧洲市场"
    JAPAN = "日本市场"
    HONG_KONG = "香港市场"
    EMERGING = "新兴市场"

@dataclass
class MarketMetrics:
    """市场指标数据"""
    region: MarketRegion
    benchmark_symbol: str
    benchmark_name: str
    
    # 表现指标
    return_1m: float    # 1个月收益率
    return_3m: float    # 3个月收益率
    return_6m: float    # 6个月收益率
    return_1y: float    # 1年收益率
    
    # 风险指标
    volatility_1m: float   # 1个月波动率
    volatility_3m: float   # 3个月波动率
    max_drawdown: float    # 最大回撤
    
    # 估值指标
    pe_ratio: Optional[float] = None     # 市盈率
    pb_ratio: Optional[float] = None     # 市净率
    dividend_yield: Optional[float] = None  # 股息率
    
    # 流动性指标
    avg_volume: float = 0.0              # 平均成交量
    turnover_rate: float = 0.0           # 换手率
    
    # 资金流向
    foreign_inflow: Optional[float] = None    # 外资流入
    institutional_holding: Optional[float] = None  # 机构持仓比例
    
    last_update: datetime = None

@dataclass
class EconomicFundamentals:
    """经济基本面数据"""
    region: MarketRegion
    
    # 增长指标
    gdp_growth: float           # GDP增长率
    gdp_growth_forecast: float  # GDP增长预测
    
    # 通胀指标
    inflation_rate: float       # 通胀率
    core_inflation: float       # 核心通胀率
    
    # 就业指标
    unemployment_rate: float    # 失业率
    employment_growth: float    # 就业增长率
    
    # 货币政策
    policy_rate: float         # 政策利率
    policy_stance: str         # 政策立场
    
    # 财政状况
    fiscal_balance: float      # 财政平衡
    debt_to_gdp: float        # 债务率
    
    # 外贸状况
    trade_balance: float       # 贸易差额
    current_account: float     # 经常账户
    
    last_update: datetime = None

@dataclass
class SectorAllocation:
    """行业配置数据"""
    region: MarketRegion
    sector_weights: Dict[str, float]  # 行业权重分布
    sector_returns: Dict[str, float]  # 行业收益表现
    sector_valuations: Dict[str, float]  # 行业估值水平
    
    leading_sectors: List[str]    # 领先行业
    lagging_sectors: List[str]    # 落后行业
    
    last_update: datetime = None

@dataclass
class ComparisonResult:
    """对比分析结果"""
    base_market: MarketRegion  # 基准市场（通常是中国A股）
    comparison_date: datetime
    
    # 综合排名
    overall_ranking: Dict[MarketRegion, int]
    attractiveness_scores: Dict[MarketRegion, float]  # 投资吸引力评分
    
    # 分维度排名
    performance_ranking: Dict[MarketRegion, int]   # 表现排名
    valuation_ranking: Dict[MarketRegion, int]     # 估值排名
    fundamentals_ranking: Dict[MarketRegion, int]  # 基本面排名
    risk_ranking: Dict[MarketRegion, int]          # 风险排名
    
    # 优势劣势分析
    china_advantages: List[str]     # 中国市场优势
    china_disadvantages: List[str]  # 中国市场劣势
    
    # 投资建议
    recommended_allocation: Dict[MarketRegion, float]  # 建议配置比例
    investment_themes: List[str]    # 投资主题
    
    # 风险提示
    key_risks: List[str]
    
    confidence_level: float

class InternationalComparator:
    """国际市场对比分析器"""
    
    def __init__(self, manager: Optional[DataSourceManager] = None):
        self.manager = manager or get_manager()
        self.tech_indicators = TechnicalIndicators()
        
        # 市场基准配置
        self.market_benchmarks = {
            MarketRegion.CHINA_A: {"symbol": "000001", "name": "上证指数"},
            MarketRegion.US: {"symbol": "^GSPC", "name": "标普500"},
            MarketRegion.EUROPE: {"symbol": "^STOXX50E", "name": "欧洲STOXX50"},
            MarketRegion.JAPAN: {"symbol": "^N225", "name": "日经225"},
            MarketRegion.HONG_KONG: {"symbol": "^HSI", "name": "恒生指数"},
            MarketRegion.EMERGING: {"symbol": "EEM", "name": "新兴市场ETF"}
        }
        
        # 评分权重配置
        self.scoring_weights = {
            "performance": 0.25,    # 表现权重
            "valuation": 0.25,      # 估值权重
            "fundamentals": 0.25,   # 基本面权重
            "risk": 0.15,          # 风险权重
            "liquidity": 0.10      # 流动性权重
        }
        
        # 行业对照表
        self.sector_mapping = {
            "Technology": "科技",
            "Healthcare": "医疗",
            "Financials": "金融",
            "Consumer Discretionary": "消费",
            "Industrials": "工业",
            "Materials": "材料",
            "Energy": "能源",
            "Utilities": "公用事业",
            "Real Estate": "房地产",
            "Communication Services": "通信"
        }

    async def compare_international_markets(self, 
                                          target_markets: Optional[List[MarketRegion]] = None,
                                          analysis_date: Optional[str] = None) -> ComparisonResult:
        """
        执行国际市场对比分析
        
        Args:
            target_markets: 目标市场列表，默认包含主要市场
            analysis_date: 分析日期，默认今日
            
        Returns:
            ComparisonResult: 对比分析结果
        """
        if not analysis_date:
            analysis_date = datetime.now().strftime('%Y-%m-%d')
            
        if not target_markets:
            target_markets = [
                MarketRegion.CHINA_A, MarketRegion.US, MarketRegion.EUROPE,
                MarketRegion.JAPAN, MarketRegion.HONG_KONG
            ]
            
        logger.info(f"Starting international markets comparison for {len(target_markets)} markets")
        
        try:
            # 并行获取各市场数据
            tasks = []
            for market in target_markets:
                task = asyncio.create_task(self._analyze_single_market(market, analysis_date))
                tasks.append(task)
                
            market_analyses = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 过滤有效结果
            valid_analyses = {}
            for i, result in enumerate(market_analyses):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to analyze {target_markets[i].value}: {result}")
                    continue
                valid_analyses[target_markets[i]] = result
                
            if len(valid_analyses) < 2:
                raise ValueError("Not enough valid market data for comparison")
                
            # 计算各维度评分和排名
            performance_scores = self._calculate_performance_scores(valid_analyses)
            valuation_scores = self._calculate_valuation_scores(valid_analyses)
            fundamentals_scores = self._calculate_fundamentals_scores(valid_analyses)
            risk_scores = self._calculate_risk_scores(valid_analyses)
            liquidity_scores = self._calculate_liquidity_scores(valid_analyses)
            
            # 综合评分计算
            overall_scores = self._calculate_overall_scores(
                performance_scores, valuation_scores, fundamentals_scores, 
                risk_scores, liquidity_scores
            )
            
            # 生成排名
            overall_ranking = self._generate_ranking(overall_scores)
            performance_ranking = self._generate_ranking(performance_scores)
            valuation_ranking = self._generate_ranking(valuation_scores)
            fundamentals_ranking = self._generate_ranking(fundamentals_scores)
            risk_ranking = self._generate_ranking(risk_scores, reverse=True)  # 风险越低越好
            
            # 优势劣势分析
            advantages, disadvantages = self._analyze_china_position(
                valid_analyses, overall_scores
            )
            
            # 投资建议生成
            allocation, themes = self._generate_investment_recommendations(
                valid_analyses, overall_scores, performance_scores
            )
            
            # 风险识别
            key_risks = self._identify_key_risks(valid_analyses, overall_scores)
            
            # 置信度评估
            confidence = self._calculate_confidence(valid_analyses)
            
            result = ComparisonResult(
                base_market=MarketRegion.CHINA_A,
                comparison_date=datetime.strptime(analysis_date, '%Y-%m-%d'),
                overall_ranking=overall_ranking,
                attractiveness_scores=overall_scores,
                performance_ranking=performance_ranking,
                valuation_ranking=valuation_ranking,
                fundamentals_ranking=fundamentals_ranking,
                risk_ranking=risk_ranking,
                china_advantages=advantages,
                china_disadvantages=disadvantages,
                recommended_allocation=allocation,
                investment_themes=themes,
                key_risks=key_risks,
                confidence_level=confidence
            )
            
            logger.info(f"International comparison completed. China A-share ranking: {overall_ranking.get(MarketRegion.CHINA_A, 'N/A')}")
            return result
            
        except Exception as e:
            logger.error(f"International comparison failed: {e}")
            raise

    async def _analyze_single_market(self, market: MarketRegion, analysis_date: str) -> Dict[str, Any]:
        """分析单个市场的完整数据"""
        try:
            # 并行获取市场数据
            tasks = [
                self._get_market_metrics(market, analysis_date),
                self._get_economic_fundamentals(market, analysis_date),
                self._get_sector_allocation(market, analysis_date)
            ]
            
            metrics, fundamentals, sectors = await asyncio.gather(*tasks)
            
            return {
                "metrics": metrics,
                "fundamentals": fundamentals,
                "sectors": sectors
            }
            
        except Exception as e:
            logger.warning(f"Failed to analyze {market.value}: {e}")
            raise

    async def _get_market_metrics(self, market: MarketRegion, analysis_date: str) -> MarketMetrics:
        """获取市场指标数据"""
        benchmark = self.market_benchmarks[market]
        symbol = benchmark["symbol"]
        
        try:
            # 获取历史价格数据
            end_date = analysis_date
            start_date = (datetime.strptime(analysis_date, '%Y-%m-%d') - timedelta(days=400)).strftime('%Y-%m-%d')
            
            response = await self.manager.get_stock_daily(symbol, start_date, end_date)
            if response.error:
                logger.warning(f"Failed to get price data for {symbol}: {response.error}")
                raise ValueError(f"No price data for {market.value}")
                
            data = response.data
            
            # 计算收益率
            current_price = data['close'].iloc[-1]
            returns = self._calculate_returns(data, current_price)
            
            # 计算波动率
            volatilities = self._calculate_volatilities(data)
            
            # 计算最大回撤
            max_drawdown = self._calculate_max_drawdown(data)
            
            # 获取估值数据
            valuation = await self._get_market_valuation(market, symbol)
            
            # 获取资金流向数据
            fund_flows = await self._get_fund_flows(market, symbol)
            
            return MarketMetrics(
                region=market,
                benchmark_symbol=symbol,
                benchmark_name=benchmark["name"],
                return_1m=returns["1m"],
                return_3m=returns["3m"],
                return_6m=returns["6m"],
                return_1y=returns["1y"],
                volatility_1m=volatilities["1m"],
                volatility_3m=volatilities["3m"],
                max_drawdown=max_drawdown,
                pe_ratio=valuation.get("pe"),
                pb_ratio=valuation.get("pb"),
                dividend_yield=valuation.get("dividend_yield"),
                avg_volume=data['volume'].tail(30).mean(),
                turnover_rate=fund_flows.get("turnover_rate", 0.0),
                foreign_inflow=fund_flows.get("foreign_inflow"),
                institutional_holding=fund_flows.get("institutional_holding"),
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )
            
        except Exception as e:
            logger.warning(f"Failed to get market metrics for {market.value}: {e}")
            # 返回默认值
            return MarketMetrics(
                region=market,
                benchmark_symbol=symbol,
                benchmark_name=benchmark["name"],
                return_1m=0.0, return_3m=0.0, return_6m=0.0, return_1y=0.0,
                volatility_1m=20.0, volatility_3m=18.0, max_drawdown=-15.0,
                avg_volume=1000000, turnover_rate=2.0,
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )

    async def _get_economic_fundamentals(self, market: MarketRegion, analysis_date: str) -> EconomicFundamentals:
        """获取经济基本面数据"""
        try:
            # 根据市场获取对应经济数据
            econ_data = await self._fetch_economic_data(market, analysis_date)
            
            return EconomicFundamentals(
                region=market,
                gdp_growth=econ_data.get("gdp_growth", 3.0),
                gdp_growth_forecast=econ_data.get("gdp_forecast", 3.2),
                inflation_rate=econ_data.get("inflation", 2.5),
                core_inflation=econ_data.get("core_inflation", 2.2),
                unemployment_rate=econ_data.get("unemployment", 5.0),
                employment_growth=econ_data.get("employment_growth", 1.5),
                policy_rate=econ_data.get("policy_rate", 4.0),
                policy_stance=econ_data.get("policy_stance", "中性"),
                fiscal_balance=econ_data.get("fiscal_balance", -3.0),
                debt_to_gdp=econ_data.get("debt_ratio", 60.0),
                trade_balance=econ_data.get("trade_balance", 0.0),
                current_account=econ_data.get("current_account", 0.5),
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )
            
        except Exception as e:
            logger.warning(f"Failed to get economic data for {market.value}: {e}")
            # 返回默认值
            return self._get_default_economic_fundamentals(market, analysis_date)

    async def _get_sector_allocation(self, market: MarketRegion, analysis_date: str) -> SectorAllocation:
        """获取行业配置数据"""
        try:
            sector_data = await self._fetch_sector_data(market, analysis_date)
            
            # 计算领先和落后行业
            sector_returns = sector_data.get("sector_returns", {})
            sorted_sectors = sorted(sector_returns.items(), key=lambda x: x[1], reverse=True)
            
            leading_count = max(2, len(sorted_sectors) // 3)
            leading_sectors = [s[0] for s in sorted_sectors[:leading_count]]
            lagging_sectors = [s[0] for s in sorted_sectors[-leading_count:]]
            
            return SectorAllocation(
                region=market,
                sector_weights=sector_data.get("sector_weights", {}),
                sector_returns=sector_returns,
                sector_valuations=sector_data.get("sector_valuations", {}),
                leading_sectors=leading_sectors,
                lagging_sectors=lagging_sectors,
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )
            
        except Exception as e:
            logger.warning(f"Failed to get sector data for {market.value}: {e}")
            return SectorAllocation(
                region=market,
                sector_weights={"科技": 20, "金融": 15, "消费": 12},
                sector_returns={"科技": 8.5, "金融": 2.3, "消费": 5.1},
                sector_valuations={"科技": 25.0, "金融": 12.0, "消费": 18.0},
                leading_sectors=["科技"],
                lagging_sectors=["金融"],
                last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
            )

    def _calculate_performance_scores(self, analyses: Dict[MarketRegion, Dict]) -> Dict[MarketRegion, float]:
        """计算表现评分"""
        scores = {}
        
        # 收集所有收益率数据
        returns_data = {}
        for market, analysis in analyses.items():
            metrics = analysis["metrics"]
            returns_data[market] = {
                "1m": metrics.return_1m,
                "3m": metrics.return_3m, 
                "6m": metrics.return_6m,
                "1y": metrics.return_1y
            }
            
        # 计算相对排名评分
        for market in analyses.keys():
            score = 0
            for period in ["1m", "3m", "6m", "1y"]:
                market_return = returns_data[market][period]
                better_count = sum(1 for other_market, data in returns_data.items() 
                                 if other_market != market and data[period] < market_return)
                relative_score = (better_count / (len(returns_data) - 1)) * 100
                
                # 时间权重：短期30%，中期40%，长期30%
                weights = {"1m": 0.15, "3m": 0.25, "6m": 0.30, "1y": 0.30}
                score += relative_score * weights[period]
                
            scores[market] = score
            
        return scores

    def _calculate_valuation_scores(self, analyses: Dict[MarketRegion, Dict]) -> Dict[MarketRegion, float]:
        """计算估值评分（估值越低越好）"""
        scores = {}
        
        # 收集估值数据
        pe_data = {}
        pb_data = {}
        
        for market, analysis in analyses.items():
            metrics = analysis["metrics"]
            if metrics.pe_ratio:
                pe_data[market] = metrics.pe_ratio
            if metrics.pb_ratio:
                pb_data[market] = metrics.pb_ratio
                
        # 计算PE相对评分（越低越好）
        for market in analyses.keys():
            score = 50.0  # 基准分
            
            if market in pe_data and pe_data:
                market_pe = pe_data[market]
                better_count = sum(1 for other_market, pe in pe_data.items() 
                                 if other_market != market and pe > market_pe)
                pe_score = (better_count / max(1, len(pe_data) - 1)) * 100
                score += (pe_score - 50) * 0.6
                
            if market in pb_data and pb_data:
                market_pb = pb_data[market]
                better_count = sum(1 for other_market, pb in pb_data.items() 
                                 if other_market != market and pb > market_pb)
                pb_score = (better_count / max(1, len(pb_data) - 1)) * 100
                score += (pb_score - 50) * 0.4
                
            scores[market] = max(0, min(100, score))
            
        return scores

    def _calculate_fundamentals_scores(self, analyses: Dict[MarketRegion, Dict]) -> Dict[MarketRegion, float]:
        """计算基本面评分"""
        scores = {}
        
        for market, analysis in analyses.items():
            fundamentals = analysis["fundamentals"]
            score = 50.0  # 基准分
            
            # GDP增长评分
            gdp_growth = fundamentals.gdp_growth
            if gdp_growth > 4:
                score += 15
            elif gdp_growth > 2:
                score += 10
            elif gdp_growth < 0:
                score -= 20
                
            # 通胀适度性评分
            inflation = fundamentals.inflation_rate
            if 1.5 <= inflation <= 3.0:  # 适度通胀
                score += 10
            elif inflation > 5:  # 高通胀
                score -= 15
                
            # 失业率评分
            unemployment = fundamentals.unemployment_rate
            if unemployment < 4:
                score += 10
            elif unemployment > 8:
                score -= 15
                
            # 财政状况评分
            debt_ratio = fundamentals.debt_to_gdp
            if debt_ratio < 60:  # 国际警戒线
                score += 10
            elif debt_ratio > 90:
                score -= 20
                
            # 贸易状况评分
            if fundamentals.current_account > 0:
                score += 5
                
            scores[market] = max(0, min(100, score))
            
        return scores

    def _calculate_risk_scores(self, analyses: Dict[MarketRegion, Dict]) -> Dict[MarketRegion, float]:
        """计算风险评分（风险越低分数越高）"""
        scores = {}
        
        # 收集风险数据
        volatility_data = {}
        drawdown_data = {}
        
        for market, analysis in analyses.items():
            metrics = analysis["metrics"]
            volatility_data[market] = metrics.volatility_3m
            drawdown_data[market] = abs(metrics.max_drawdown)
            
        # 计算风险相对评分
        for market in analyses.keys():
            score = 50.0
            
            # 波动率评分（越低越好）
            market_vol = volatility_data[market]
            better_count = sum(1 for other_market, vol in volatility_data.items() 
                             if other_market != market and vol > market_vol)
            vol_score = (better_count / max(1, len(volatility_data) - 1)) * 100
            score += (vol_score - 50) * 0.6
            
            # 回撤评分（越小越好）
            market_dd = drawdown_data[market]
            better_count = sum(1 for other_market, dd in drawdown_data.items() 
                             if other_market != market and dd > market_dd)
            dd_score = (better_count / max(1, len(drawdown_data) - 1)) * 100
            score += (dd_score - 50) * 0.4
            
            scores[market] = max(0, min(100, score))
            
        return scores

    def _calculate_liquidity_scores(self, analyses: Dict[MarketRegion, Dict]) -> Dict[MarketRegion, float]:
        """计算流动性评分"""
        scores = {}
        
        for market, analysis in analyses.items():
            metrics = analysis["metrics"]
            score = 50.0
            
            # 换手率评分
            if metrics.turnover_rate > 3:
                score += 15
            elif metrics.turnover_rate > 1:
                score += 10
            elif metrics.turnover_rate < 0.5:
                score -= 10
                
            # 成交量评分（简化实现）
            if metrics.avg_volume > 1000000:
                score += 10
                
            scores[market] = max(0, min(100, score))
            
        return scores

    def _calculate_overall_scores(self, performance: Dict, valuation: Dict, 
                                fundamentals: Dict, risk: Dict, liquidity: Dict) -> Dict[MarketRegion, float]:
        """计算综合评分"""
        overall_scores = {}
        
        all_markets = set(performance.keys()) | set(valuation.keys()) | set(fundamentals.keys())
        
        for market in all_markets:
            score = (
                performance.get(market, 50) * self.scoring_weights["performance"] +
                valuation.get(market, 50) * self.scoring_weights["valuation"] +
                fundamentals.get(market, 50) * self.scoring_weights["fundamentals"] +
                risk.get(market, 50) * self.scoring_weights["risk"] +
                liquidity.get(market, 50) * self.scoring_weights["liquidity"]
            )
            overall_scores[market] = score
            
        return overall_scores

    def _generate_ranking(self, scores: Dict[MarketRegion, float], reverse: bool = False) -> Dict[MarketRegion, int]:
        """生成排名"""
        sorted_markets = sorted(scores.items(), key=lambda x: x[1], reverse=not reverse)
        ranking = {}
        for i, (market, score) in enumerate(sorted_markets, 1):
            ranking[market] = i
        return ranking

    def _analyze_china_position(self, analyses: Dict[MarketRegion, Dict], 
                               overall_scores: Dict[MarketRegion, float]) -> Tuple[List[str], List[str]]:
        """分析中国市场的优势和劣势"""
        advantages = []
        disadvantages = []
        
        if MarketRegion.CHINA_A not in analyses:
            return advantages, disadvantages
            
        china_analysis = analyses[MarketRegion.CHINA_A]
        china_metrics = china_analysis["metrics"]
        china_fundamentals = china_analysis["fundamentals"]
        
        # GDP增长优势
        if china_fundamentals.gdp_growth > 4:
            advantages.append("GDP增长率领先全球")
            
        # 估值优势
        if china_metrics.pe_ratio and china_metrics.pe_ratio < 15:
            advantages.append("估值水平相对合理")
            
        # 流动性优势
        if china_metrics.turnover_rate > 2:
            advantages.append("市场流动性充裕")
            
        # 政策空间优势
        if china_fundamentals.debt_to_gdp < 70:
            advantages.append("政策调节空间充足")
            
        # 劣势分析
        china_score = overall_scores.get(MarketRegion.CHINA_A, 50)
        avg_score = sum(overall_scores.values()) / len(overall_scores)
        
        if china_score < avg_score:
            disadvantages.append("综合吸引力低于平均水平")
            
        if china_metrics.volatility_3m > 25:
            disadvantages.append("市场波动率偏高")
            
        return advantages, disadvantages

    def _generate_investment_recommendations(self, analyses: Dict[MarketRegion, Dict],
                                           overall_scores: Dict[MarketRegion, float],
                                           performance_scores: Dict[MarketRegion, float]) -> Tuple[Dict[MarketRegion, float], List[str]]:
        """生成投资建议"""
        # 基于综合评分的配置建议
        total_score = sum(overall_scores.values())
        allocation = {}
        
        for market, score in overall_scores.items():
            weight = (score / total_score) * 100
            allocation[market] = round(weight, 1)
            
        # 投资主题识别
        themes = []
        
        # 基于表现排名识别主题
        sorted_performance = sorted(performance_scores.items(), key=lambda x: x[1], reverse=True)
        top_market = sorted_performance[0][0]
        
        if top_market == MarketRegion.US:
            themes.append("科技创新引领")
        elif top_market == MarketRegion.CHINA_A:
            themes.append("新兴经济增长")
        elif top_market == MarketRegion.EUROPE:
            themes.append("价值回归机会")
            
        # 基于估值和增长的主题
        for market, analysis in analyses.items():
            fundamentals = analysis["fundamentals"]
            if fundamentals.gdp_growth > 4:
                themes.append("高增长市场配置")
                break
                
        return allocation, themes

    def _identify_key_risks(self, analyses: Dict[MarketRegion, Dict], 
                          overall_scores: Dict[MarketRegion, float]) -> List[str]:
        """识别关键风险"""
        risks = []
        
        # 通胀风险
        high_inflation_count = 0
        for market, analysis in analyses.items():
            if analysis["fundamentals"].inflation_rate > 4:
                high_inflation_count += 1
                
        if high_inflation_count >= len(analyses) // 2:
            risks.append("全球通胀压力上升")
            
        # 政策分化风险
        policy_stances = [analysis["fundamentals"].policy_stance for analysis in analyses.values()]
        if len(set(policy_stances)) > 2:
            risks.append("主要经济体政策分化")
            
        # 地缘政治风险
        risks.append("地缘政治不确定性")
        
        # 市场波动风险
        avg_volatility = sum(analysis["metrics"].volatility_3m for analysis in analyses.values()) / len(analyses)
        if avg_volatility > 25:
            risks.append("市场波动率处于高位")
            
        return risks

    def _calculate_confidence(self, analyses: Dict[MarketRegion, Dict]) -> float:
        """计算分析置信度"""
        confidence_factors = []
        
        # 数据完整性
        for market, analysis in analyses.items():
            completeness = 0
            
            if analysis["metrics"].pe_ratio is not None:
                completeness += 0.3
            if analysis["metrics"].foreign_inflow is not None:
                completeness += 0.2
            if analysis["fundamentals"].gdp_growth != 0:
                completeness += 0.3
            if analysis["sectors"].sector_weights:
                completeness += 0.2
                
            confidence_factors.append(completeness)
            
        # 数据时效性
        now = datetime.now()
        for analysis in analyses.values():
            age = (now - analysis["metrics"].last_update).days
            if age <= 7:
                confidence_factors.append(0.9)
            elif age <= 30:
                confidence_factors.append(0.8)
            else:
                confidence_factors.append(0.6)
                
        return sum(confidence_factors) / len(confidence_factors) * 100 if confidence_factors else 50.0

    # 数据获取辅助方法
    def _calculate_returns(self, data: pd.DataFrame, current_price: float) -> Dict[str, float]:
        """计算各期收益率"""
        returns = {}
        
        periods = {"1m": 20, "3m": 60, "6m": 120, "1y": 250}
        
        for period_name, days in periods.items():
            if len(data) > days:
                past_price = data['close'].iloc[-(days+1)]
                ret = (current_price / past_price - 1) * 100
                returns[period_name] = ret
            else:
                returns[period_name] = 0.0
                
        return returns

    def _calculate_volatilities(self, data: pd.DataFrame) -> Dict[str, float]:
        """计算波动率"""
        data['returns'] = data['close'].pct_change()
        
        volatilities = {}
        periods = {"1m": 20, "3m": 60}
        
        for period_name, days in periods.items():
            if len(data) > days:
                period_vol = data['returns'].tail(days).std() * np.sqrt(250) * 100
                volatilities[period_name] = period_vol
            else:
                volatilities[period_name] = 20.0
                
        return volatilities

    def _calculate_max_drawdown(self, data: pd.DataFrame) -> float:
        """计算最大回撤"""
        cumulative = (1 + data['close'].pct_change()).cumprod()
        rolling_max = cumulative.expanding().max()
        drawdown = (cumulative / rolling_max - 1) * 100
        return drawdown.min()

    async def _get_market_valuation(self, market: MarketRegion, symbol: str) -> Dict[str, Optional[float]]:
        """获取市场估值数据（模拟实现）"""
        valuation_defaults = {
            MarketRegion.CHINA_A: {"pe": 13.5, "pb": 1.4, "dividend_yield": 2.3},
            MarketRegion.US: {"pe": 21.8, "pb": 3.2, "dividend_yield": 1.8},
            MarketRegion.EUROPE: {"pe": 15.2, "pb": 1.8, "dividend_yield": 3.1},
            MarketRegion.JAPAN: {"pe": 16.5, "pb": 1.2, "dividend_yield": 2.4},
            MarketRegion.HONG_KONG: {"pe": 11.2, "pb": 0.9, "dividend_yield": 3.8}
        }
        return valuation_defaults.get(market, {"pe": 18.0, "pb": 2.0, "dividend_yield": 2.5})

    async def _get_fund_flows(self, market: MarketRegion, symbol: str) -> Dict[str, Optional[float]]:
        """获取资金流向数据（模拟实现）"""
        flow_defaults = {
            MarketRegion.CHINA_A: {"turnover_rate": 3.2, "foreign_inflow": 150, "institutional_holding": 35},
            MarketRegion.US: {"turnover_rate": 1.8, "foreign_inflow": -50, "institutional_holding": 65},
            MarketRegion.EUROPE: {"turnover_rate": 1.2, "foreign_inflow": 20, "institutional_holding": 45},
            MarketRegion.JAPAN: {"turnover_rate": 0.8, "foreign_inflow": 30, "institutional_holding": 40},
            MarketRegion.HONG_KONG: {"turnover_rate": 2.5, "foreign_inflow": 80, "institutional_holding": 55}
        }
        return flow_defaults.get(market, {"turnover_rate": 2.0, "foreign_inflow": 0, "institutional_holding": 50})

    async def _fetch_economic_data(self, market: MarketRegion, date: str) -> Dict[str, float]:
        """获取经济数据（模拟实现）"""
        econ_defaults = {
            MarketRegion.CHINA_A: {
                "gdp_growth": 5.2, "gdp_forecast": 5.0, "inflation": 2.1, "core_inflation": 1.8,
                "unemployment": 5.1, "employment_growth": 1.2, "policy_rate": 4.35, "policy_stance": "稳健",
                "fiscal_balance": -2.8, "debt_ratio": 52.6, "trade_balance": 45.2, "current_account": 1.8
            },
            MarketRegion.US: {
                "gdp_growth": 2.8, "gdp_forecast": 2.5, "inflation": 3.2, "core_inflation": 2.8,
                "unemployment": 3.8, "employment_growth": 2.1, "policy_rate": 5.25, "policy_stance": "紧缩",
                "fiscal_balance": -5.2, "debt_ratio": 98.5, "trade_balance": -82.3, "current_account": -3.1
            }
        }
        return econ_defaults.get(market, {
            "gdp_growth": 2.5, "gdp_forecast": 2.3, "inflation": 2.8, "core_inflation": 2.5,
            "unemployment": 6.2, "employment_growth": 1.0, "policy_rate": 4.0, "policy_stance": "中性",
            "fiscal_balance": -3.5, "debt_ratio": 65.0, "trade_balance": 0.0, "current_account": 0.0
        })

    async def _fetch_sector_data(self, market: MarketRegion, date: str) -> Dict[str, Any]:
        """获取行业数据（模拟实现）"""
        return {
            "sector_weights": {"科技": 22.5, "金融": 18.3, "消费": 15.2, "工业": 12.8},
            "sector_returns": {"科技": 8.5, "金融": 2.3, "消费": 5.1, "工业": 4.2},
            "sector_valuations": {"科技": 25.0, "金融": 12.0, "消费": 18.0, "工业": 16.5}
        }

    def _get_default_economic_fundamentals(self, market: MarketRegion, analysis_date: str) -> EconomicFundamentals:
        """获取默认经济基本面数据"""
        return EconomicFundamentals(
            region=market,
            gdp_growth=3.0, gdp_growth_forecast=2.8, inflation_rate=2.5, core_inflation=2.2,
            unemployment_rate=5.5, employment_growth=1.2, policy_rate=4.0, policy_stance="中性",
            fiscal_balance=-3.2, debt_to_gdp=60.0, trade_balance=0.0, current_account=0.5,
            last_update=datetime.strptime(analysis_date, '%Y-%m-%d')
        )