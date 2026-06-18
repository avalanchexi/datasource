#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Pring Result Contract - V3.1 解耦架构
定义Pring分析结果的标准化JSON格式
"""

from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any


class InventoryCycleLayer(BaseModel):
    """第一层：库存周期分析"""
    cycle_stage: str  # 主动补库/被动补库/主动去库/被动去库
    commodity_bias: str  # 偏牛/中性/偏熊
    fundamental_score: float  # Max 60
    indicators: Optional[Dict[str, Any]] = None  # PPI, PMI, 工增, BDI, CPI
    score_details: Dict[str, Any] = Field(default_factory=dict)
    analysis: Optional[str] = None
    data_source: Optional[str] = None
    update_time: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "cycle_stage": "被动补库存",
                "commodity_bias": "偏牛",
                "fundamental_score": 35.0,
                "indicators": {
                    "PPI": {"weight": 0.30, "score": 0, "detail": "N/A"},
                    "PMI": {"weight": 0.25, "score": 0, "detail": "N/A"},
                    "工业增加值": {"weight": 0.20, "score": 0, "detail": "N/A"},
                    "BDI": {"weight": 0.15, "score": 0, "detail": "N/A"},
                    "CPI": {"weight": 0.10, "score": 0, "detail": "N/A"}
                }
            }
        }


class MonetaryCycleLayer(BaseModel):
    """第二层：货币周期叠加"""
    cycle_stage: str  # 宽松/中性/收紧
    equity_bias: str  # 利好权益/中性/压制权益
    bond_bias: str  # 债券相对占优/中性/债券相对弱势
    monetary_score: float  # Max 100
    indicators: Optional[Dict[str, Any]] = None  # 降准, 降息, TSF, M2
    score_details: Dict[str, Any] = Field(default_factory=dict)
    analysis: Optional[str] = None
    data_source: Optional[str] = None
    websearch_needed: Dict[str, Any] = Field(default_factory=dict)
    websearch_required: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "example": {
                "cycle_stage": "收紧",
                "equity_bias": "压制权益",
                "bond_bias": "债券相对占优",
                "monetary_score": 0.0,
                "indicators": {
                    "存款准备金率变化": {
                        "weight": 0.30,
                        "score": 0,
                        "detail": "数据缺失，需WebSearch补充"
                    },
                    "7天逆回购利率": {
                        "weight": 0.30,
                        "score": 0,
                        "detail": "0/30分 (变化0bp)"
                    },
                    "TSF增速": {
                        "weight": 0.25,
                        "score": 0,
                        "detail": "数据缺失，需WebSearch补充"
                    },
                    "M2增速": {
                        "weight": 0.15,
                        "score": 0,
                        "detail": "数据缺失，需WebSearch补充"
                    }
                },
                "websearch_needed": []
            }
        }


class PringFinalLayer(BaseModel):
    """第三层：Pring六阶段最终判定"""
    base_stage: str  # 第Ⅰ-Ⅵ阶段 (基础判定)
    final_stage: str  # 第Ⅰ-Ⅵ阶段 (货币修正后)
    confidence: Optional[float] = None  # 0.0-1.0
    monetary_adjustment: float  # 货币修正幅度(%)
    asset_allocation: Optional[Dict[str, str]] = None
    allocation_suggestion: Optional[str] = None  # 债券/股票/商品配置建议
    base_confidence: Optional[float] = None
    final_confidence: Optional[float] = None
    analysis: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "base_stage": "第Ⅵ阶段",
                "final_stage": "第Ⅵ阶段",
                "confidence": 0.90,
                "monetary_adjustment": 0.0,
                "asset_allocation": {
                    "债券": "短久期",
                    "股票": "低配",
                    "商品": "低配"
                }
            }
        }


class PringResultContract(BaseModel):
    """Pring分析结果完整合约"""
    metadata: Dict = Field(
        description="元数据: analysis_date, data_source, framework_version"
    )
    layer_1_inventory_cycle: InventoryCycleLayer
    layer_2_monetary_cycle: MonetaryCycleLayer
    layer_3_pring_final: PringFinalLayer

    # 最终结果(快速访问)
    stage: str
    confidence: float
    asset_signals: Dict[str, str]
    allocation_suggestion: Optional[str] = None
    asset_recommendations: Dict[str, str] = Field(default_factory=dict)
    asset_allocation_pct: Dict[str, str] = Field(default_factory=dict)
    analysis_date: Optional[str] = None
    commodity_bias: Optional[str] = None
    commodity_signal: Optional[str] = None
    current_stage: Optional[str] = None
    data_period: Optional[str] = None
    enhancement_notes: Optional[str] = None
    final_stage: Optional[str] = None
    inventory_cycle_stage: Optional[str] = None
    leading_summary: Optional[str] = None
    methodology: Optional[str] = None
    recommendation: Optional[str] = None
    stage_description: Optional[str] = None
    commodity_signal_score: Optional[float] = None
    inventory_cycle_score: Optional[float] = None
    technical_score: Optional[float] = None
    confirm_signals: List[Any] = Field(default_factory=list)
    deny_signals: List[Any] = Field(default_factory=list)
    focus_assets: List[Any] = Field(default_factory=list)
    macro_stage: Dict[str, Any] = Field(default_factory=dict)
    # 扩展字段（Stage3 V4.3）
    pending_websearch: List[Any] = Field(default_factory=list)
    data_completeness: Optional[float] = None
    fallback_used: bool = False
    leading_indicator: Optional[Dict[str, Any]] = None
    weights_version: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "metadata": {
                    "analysis_date": "2025-11-10",
                    "data_source": "AKShare实时数据",
                    "framework_version": "V4.0三层框架"
                },
                "layer_1_inventory_cycle": {
                    "cycle_stage": "被动补库存",
                    "commodity_bias": "偏牛",
                    "fundamental_score": 35.0,
                    "indicators": {}
                },
                "layer_2_monetary_cycle": {
                    "cycle_stage": "收紧",
                    "equity_bias": "压制权益",
                    "bond_bias": "债券相对占优",
                    "monetary_score": 0.0,
                    "indicators": {},
                    "websearch_needed": []
                },
                "layer_3_pring_final": {
                    "base_stage": "第Ⅵ阶段",
                    "final_stage": "第Ⅵ阶段",
                    "confidence": 0.90,
                    "monetary_adjustment": 0.0,
                    "asset_allocation": {
                        "债券": "短久期",
                        "股票": "低配",
                        "商品": "低配"
                    }
                },
                "stage": "第Ⅵ阶段",
                "confidence": 0.90,
                "asset_signals": {
                    "bond": "Neutral",
                    "stock": "Bearish",
                    "commodity": "Bearish"
                },
                "asset_allocation_pct": {
                    "bond": "40-50%",
                    "stock": "30-40%",
                    "commodity": "10-15%",
                    "cash": "5-10%"
                }
            }
        }
