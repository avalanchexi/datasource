#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Market Data Contract - V3.1 解耦架构
定义市场数据的标准化JSON格式
"""

import re
from typing import Any, Dict, List, Optional

try:
    from pydantic import BaseModel, Field, field_validator
except ImportError:
    from pydantic import BaseModel, Field, validator as _pydantic_validator

    def _amount_field_validator(*fields: str):
        return _pydantic_validator(*fields, pre=True, allow_reuse=True)
else:

    def _amount_field_validator(*fields: str):
        return field_validator(*fields, mode="before")


class StockIndexData(BaseModel):
    """股票指数数据"""
    symbol: str
    name: str
    current_price: float
    change_5d: Optional[float] = None
    change_120d: Optional[float] = None
    above_ma50: bool
    above_ma200: bool
    ma50_slope: float
    volatility_30d: float
    trend_score: int  # -2 to +2
    trend_label: str  # 熊/震荡/牛
    source: str


class CommodityData(BaseModel):
    """商品数据"""
    symbol: str
    name: str
    current_price: Optional[float] = None
    unit: str  # $/oz, $/barrel, etc.
    as_of_date: Optional[str] = None
    confidence: Optional[float] = None
    daily_change_basis: Optional[str] = None
    daily_change: Optional[float] = None
    date: Optional[str] = None
    is_estimated: bool = False
    ytd_change: Optional[float] = None
    change_120d: Optional[float] = None
    change_120d_basis: Optional[str] = None
    trend: str
    source: str
    source_url: Optional[str] = None
    timestamp: str
    stage_task_id: Optional[str] = None
    trend_history_confidence: Optional[str] = None
    note: Optional[str] = None


class ForexData(BaseModel):
    """汇率数据"""
    pair: str
    name: str
    current_rate: float
    daily_change: Optional[float] = None
    change_120d: Optional[float] = None
    change_120d_base_date: Optional[str] = None
    change_120d_basis: Optional[str] = None
    daily_change_base_date: Optional[str] = None
    daily_change_basis: Optional[str] = None
    date: Optional[str] = None
    trend: str
    source: str
    source_url: Optional[str] = None
    as_of_date: Optional[str] = None
    stage_task_id: Optional[str] = None
    trend_history_confidence: Optional[str] = None
    confidence: Optional[float] = None
    is_estimated: bool = False
    note: Optional[str] = None


class BondYieldData(BaseModel):
    """债券收益率数据"""
    symbol: str
    name: str
    current_yield: Optional[float] = None
    change_5d_bp: Optional[float] = None
    change_120d_bp: Optional[float] = None
    trend: str
    source: str
    date: Optional[str] = None
    as_of_date: Optional[str] = None
    report_period: Optional[str] = None
    is_estimated: bool = False
    estimation_method: Optional[str] = None
    source_url: Optional[str] = None
    stage_task_id: Optional[str] = None
    trend_history_confidence: Optional[str] = None
    note: Optional[str] = None


class FundFlowData(BaseModel):
    """资金流向数据"""

    type: str  # northbound/southbound/etf/margin
    recent_5d: Optional[float] = None
    total_120d: Optional[float] = None
    trend: str
    source: str
    source_url: Optional[str] = None
    as_of_date: Optional[str] = None
    claimed_source_tier: Optional[str] = None
    date: Optional[str] = None
    estimation_method: Optional[str] = None
    metric_basis: Optional[str] = None
    source_tier: Optional[str] = None
    window_evidence: Optional[str] = None
    is_estimated: bool = False
    manual_required: bool = False
    note: Optional[str] = None
    stage_task_id: Optional[str] = None

    @staticmethod
    def _parse_amount(value: Optional[Any]) -> Optional[float]:
        """将字符串金额（含单位/符号）解析为浮点数，以“亿元”为统一单位"""
        if value is None:
            return None

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            text = value.strip().replace(',', '')
            if not text or text.upper() == 'N/A':
                return None

            multiplier = 1.0
            if '万亿' in text:
                multiplier = 10000.0
            elif '千亿' in text:
                multiplier = 1000.0
            elif '亿' in text:
                multiplier = 1.0

            match = re.search(r'[-+]?\d+(?:\.\d+)?', text)
            if not match:
                return None

            amount = float(match.group()) * multiplier

            # 若原文未显式带负号，但包含“净流出”等关键词，则补充符号
            if (
                ('净流出' in text or '流出' in text)
                and amount > 0
                and '-' not in match.group()
            ):
                amount = -amount

            return amount

        return None

    @_amount_field_validator('recent_5d', 'total_120d')
    def _coerce_amount(cls, value: Optional[Any]) -> Optional[float]:
        return cls._parse_amount(value)


class FinancialNewsItem(BaseModel):
    """财经要闻"""
    title: str
    category: str
    date: str
    source: str


class MacroIndicatorData(BaseModel):
    """宏观经济指标数据 - Pring第一层(库存周期)"""
    indicator_name: str  # PPI/PMI/工业增加值/BDI/CPI
    current_value: Optional[float] = None
    yoy_month: Optional[float] = None  # 当月同比（如工业增加值）
    yoy_ytd: Optional[float] = None    # 累计同比（如1-12月）
    previous_value: Optional[float] = None
    change_rate: Optional[float] = None  # 同比/环比增速
    unit: str  # %/点
    date: str  # 数据日期
    as_of_date: Optional[str] = None    # 数据口径日期/报告期
    value_type: Optional[str] = None    # 口径标记: yoy_month/yoy_ytd 等
    source: str
    is_estimated: bool = False
    estimation_method: Optional[str] = None
    report_period: Optional[str] = None
    source_url: Optional[str] = None
    confidence: Optional[float] = None
    is_stale: bool = False
    expected_period: Optional[str] = None
    stale_reason: Optional[str] = None
    stage_task_id: Optional[str] = None
    note: Optional[str] = None


class MonetaryPolicyData(BaseModel):
    """货币政策数据 - Pring第二层(货币周期)"""
    policy_name: str  # 存准率/7天逆回购/TSF/M2
    current_value: Optional[float] = None
    change_from_120d: Optional[float] = None  # 120日变化
    unit: str  # %/bp
    date: str
    as_of_date: Optional[str] = None    # 数据口径日期/报告期
    rrr_type: Optional[str] = None      # 存准率口径: weighted/statutory 等
    source: str
    is_estimated: bool = False
    estimation_method: Optional[str] = None
    report_period: Optional[str] = None
    source_url: Optional[str] = None
    trend_history_confidence: Optional[str] = None
    confidence: Optional[float] = None
    is_stale: bool = False
    expected_period: Optional[str] = None
    stale_reason: Optional[str] = None
    note: Optional[str] = None
    stage_task_id: Optional[str] = None


class MarketDataContract(BaseModel):
    """市场数据完整合约"""
    metadata: Dict = Field(
        description=(
            "元数据: date, start_date, end_date, generation_time, "
            "data_completeness"
        )
    )
    missing_items: List[Any] = Field(default_factory=list)
    stock_indices: List[StockIndexData]
    commodities: List[CommodityData]
    forex: List[ForexData]
    bonds: List[BondYieldData]
    fund_flow: Dict[str, FundFlowData]
    financial_news: List[FinancialNewsItem] = Field(default_factory=list)
    macro_indicators: Dict[str, MacroIndicatorData] = Field(
        default_factory=dict
    )
    monetary_policy: Dict[str, MonetaryPolicyData] = Field(
        default_factory=dict
    )
    derived_metrics: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "example": {
                "metadata": {
                    "date": "2025-11-10",
                    "start_date": "2025-07-13",
                    "end_date": "2025-11-10",
                    "generation_time": "2025-11-10T14:00:00",
                    "data_completeness": 0.75
                },
                "stock_indices": [
                    {
                        "symbol": "000300",
                        "name": "沪深300",
                        "current_price": 3950.5,
                        "change_5d": 0.5,
                        "change_120d": 16.5,
                        "above_ma50": True,
                        "above_ma200": True,
                        "ma50_slope": 9.2527,
                        "volatility_30d": 16.8,
                        "trend_score": 2,
                        "trend_label": "牛",
                        "source": "tushare"
                    }
                ],
                "commodities": [
                    {
                        "symbol": "GC=F",
                        "name": "COMEX黄金",
                        "current_price": 4070.72,
                        "unit": "$/oz",
                        "daily_change": 1.52,
                        "ytd_change": 50.32,
                        "trend": "强烈上涨",
                        "source": "MCP WebFetch(Investing.com实时)",
                        "timestamp": "2025-11-10"
                    }
                ],
                "forex": [
                    {
                        "pair": "USDCNY",
                        "name": "USD/CNY在岸",
                        "current_rate": 7.1181,
                        "daily_change": -0.75,
                        "change_120d": -0.70,
                        "trend": "贬值",
                        "source": "international_finance"
                    }
                ],
                "bonds": [
                    {
                        "symbol": "US10Y",
                        "name": "美国10年期国债",
                        "current_yield": 4.093,
                        "change_5d_bp": -1.3,
                        "change_120d_bp": -33.4,
                        "trend": "平稳",
                        "source": "international_finance",
                        "is_estimated": False
                    }
                ],
                "fund_flow": {
                    "northbound": {
                        "type": "northbound",
                        "recent_5d": 132.6,
                        "total_120d": 845.2,
                        "trend": "流入",
                        "source": "MCP WebSearch实时获取",
                        "note": "来源:东方财富网"
                    }
                },
                "financial_news": []
            }
        }
