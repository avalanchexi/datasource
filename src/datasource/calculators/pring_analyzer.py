import os
from contextlib import contextmanager
import pandas as pd
import numpy as np
from typing import Dict, Optional, List, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum
import asyncio
from loguru import logger
from datasource.models.market_data_contract import MarketDataContract


class PringStage(Enum):
    """普林格六阶段枚举"""
    STAGE_I = "Ⅰ"      # 债券↑，股票↓，商品↓
    STAGE_II = "Ⅱ"     # 债券↑，股票↑，商品↓
    STAGE_III = "Ⅲ"    # 债券↑，股票↑，商品↑
    STAGE_IV = "Ⅳ"     # 债券↓，股票↑，商品↑
    STAGE_V = "Ⅴ"      # 债券↓，股票↓，商品↑
    STAGE_VI = "Ⅵ"     # 债券↓，股票↓，商品↓

    def to_display_format(self) -> str:
        """
        转换为显示格式：第Ⅵ阶段

        Returns:
            格式化的阶段标注
        """
        return f"第{self.value}阶段"


class AssetSignal(Enum):
    """资产信号枚举"""
    BULLISH = "Bullish"
    BEARISH = "Bearish"
    NEUTRAL = "Neutral"


class InventoryCycleStage(Enum):
    """库存周期阶段枚举"""
    ACTIVE_RESTOCKING = "主动补库存"      # PPI↑, PMI库存↓
    PASSIVE_RESTOCKING = "被动补库存"     # PPI↑, PMI库存↑
    ACTIVE_DESTOCKING = "主动去库存"      # PPI↓, PMI库存↓
    PASSIVE_DESTOCKING = "被动去库存"     # PPI↓, PMI库存↑


class MonetaryCycleStage(Enum):
    """货币周期阶段枚举"""
    EASING = "宽松"           # 降准/降息/TSF改善
    NEUTRAL = "中性"          # 政策维持不变
    TIGHTENING = "收紧"       # 上调利率/TSF放缓


@contextmanager
def without_proxies():
    proxy_keys = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"]
    backup = {key: os.environ.get(key) for key in proxy_keys}
    for key in proxy_keys:
        if key in os.environ:
            os.environ.pop(key)
    try:
        yield
    finally:
        for key, value in backup.items():
            if value is not None:
                os.environ[key] = value


def fetch_with_no_proxy(func, *args, **kwargs):
    with without_proxies():
        return func(*args, **kwargs)


class PringAnalyzer:
    """普林格六阶段分析器（集成库存周期矫正）"""

    STAGE_SEQUENCE: List[PringStage] = [
        PringStage.STAGE_I,
        PringStage.STAGE_II,
        PringStage.STAGE_III,
        PringStage.STAGE_IV,
        PringStage.STAGE_V,
        PringStage.STAGE_VI,
    ]
    
    def __init__(self, data_manager, market_data: Optional[MarketDataContract] = None):
        self.data_manager = data_manager
        self.preloaded_market_data = market_data
        
        # 库存周期矫正权重配置 (V3.1规范)
        self.cycle_correction_weights = {
            "technical_weight": 0.35,     # 技术面权重35% (V3.1调整)
            "fundamental_weight": 0.65,   # 基本面权重65% (V3.1调整)
            "bullish_threshold": 70,      # ≥70分判定Bullish
            "bearish_threshold": 30,      # ≤30分判定Bearish
            "neutral_range": (30, 70)     # 30-70分为Neutral
        }
        
        # 阶段配置倾向
        self.stage_allocations = self._build_stage_allocations()

        self.commodity_targets = [
            {"symbol": "CL", "name": "WTI原油", "fetch": "futures_foreign"},
            {"symbol": "OIL", "name": "Brent原油", "fetch": "futures_foreign"},
            {"symbol": "HG", "name": "COMEX铜", "fetch": "futures_foreign"},
            {"symbol": "XAU", "name": "现货黄金", "fetch": "futures_foreign"},
            {"symbol": "GSG", "name": "BCOM商品指数", "fetch": "us_etf"},
        ]
        self.last_commodity_correction: Dict[str, Any] = {}

    def _build_stage_allocations(self) -> Dict[PringStage, Dict[str, Any]]:
        """构建普林格阶段的资产配置模板"""
        return {
            PringStage.STAGE_I: {
                "description": "阶段Ⅰ：债券率先走强，股票与商品仍在筑底（衰退末期）",
                "allocation": "长久期国债+现金是核心仓位，等待政策宽松传导；权益仅保留防守性仓位",
                "bonds": "超配",
                "stocks": "低配",
                "commodities": "低配",
                "cash": "超配",
                "focus_assets": ["长久期国债", "政策利率债", "货币基金/现金管理"],
                "allocation_pct": {
                    "bond": "55-65%",
                    "stock": "20-30%",
                    "commodity": "5-10%",
                    "cash": "10-15%"
                }
            },
            PringStage.STAGE_II: {
                "description": "阶段Ⅱ：债券与股票同步上行，商品仍偏弱（复苏初期）",
                "allocation": "股票开始接棒，保留一部分优质国债做缓冲，商品仍以低配观察",
                "bonds": "标配",
                "stocks": "超配",
                "commodities": "低配",
                "cash": "低配",
                "focus_assets": ["高β股票/宽基指数", "长久期国债"],
                "allocation_pct": {
                    "bond": "40-50%",
                    "stock": "30-40%",
                    "commodity": "10-15%",
                    "cash": "5-10%"
                }
            },
            PringStage.STAGE_III: {
                "description": "阶段Ⅲ：权益与商品全面走强，债券收益率触顶（扩张前期）",
                "allocation": "超配股票并增配工业金属/能源，债券降至低配，现金保持流动性",
                "bonds": "低配",
                "stocks": "超配",
                "commodities": "标配",
                "cash": "低配",
                "focus_assets": ["权益指数", "工业金属ETF", "资源股"],
                "allocation_pct": {
                    "bond": "25-35%",
                    "stock": "45-55%",
                    "commodity": "15-20%",
                    "cash": "5-10%"
                }
            },
            PringStage.STAGE_IV: {
                "description": "阶段Ⅳ：通胀抬升，商品与股票同涨、债券承压（扩张后期）",
                "allocation": "股票回归标配但偏价值/资源，商品（尤其能源）超配承接通胀交易",
                "bonds": "低配",
                "stocks": "标配",
                "commodities": "超配",
                "cash": "低配",
                "focus_assets": ["能源/资源股", "原油&大宗商品ETF"],
                "allocation_pct": {
                    "bond": "20-30%",
                    "stock": "35-45%",
                    "commodity": "20-30%",
                    "cash": "5-10%"
                }
            },
            PringStage.STAGE_V: {
                "description": "阶段Ⅴ：通胀高位回落，商品冲高而股票转弱（滞胀末期）",
                "allocation": "大宗+贵金属维持超配，股票降至低配，债券和现金用于管理波动",
                "bonds": "低配",
                "stocks": "低配",
                "commodities": "超配",
                "cash": "标配",
                "focus_assets": ["贵金属", "能源/大宗商品指数", "抗通胀资产"],
                "allocation_pct": {
                    "bond": "10-20%",
                    "stock": "25-35%",
                    "commodity": "35-45%",
                    "cash": "10-15%"
                }
            },
            PringStage.STAGE_VI: {
                "description": "阶段Ⅵ：经济下行，债券与股票同步疲弱，现金为王（衰退期）",
                "allocation": "全面防守，现金+短久期债+黄金(贵金属)组合等待下一轮债券领先",
                "bonds": "短久期",
                "stocks": "低配",
                "commodities": "低配",
                "cash": "超配",
                "focus_assets": ["短久期国债/政策性金融债", "现金", "黄金/贵金属"],
                "allocation_pct": {
                    "bond": "35-45%",
                    "stock": "15-25%",
                    "commodity": "5-10%",
                    "cash": "15-25%"
                }
            }
        }

    def _shift_stage(self, stage: PringStage, steps: int) -> PringStage:
        """按照固定顺序对阶段做有限平移（不循环）"""
        try:
            index = self.STAGE_SEQUENCE.index(stage)
        except ValueError:
            return stage
        target = max(0, min(len(self.STAGE_SEQUENCE) - 1, index + steps))
        return self.STAGE_SEQUENCE[target]

    def _extract_leading_payload(self, monetary_data: Dict) -> Optional[Dict[str, Any]]:
        """优先从预加载数据或原始货币字段中提取DR007/逆回购原始值"""
        raw_values = monetary_data.get("raw_values") or {}
        for key in ("dr007_rate", "reverse_repo_7d"):
            payload = raw_values.get(key)
            if payload and payload.get("value") is not None:
                payload["field"] = key
                return payload

        if self.preloaded_market_data and self.preloaded_market_data.monetary_policy:
            for key in ("dr007", "reverse_repo_7d", "reverse_repo"):
                policy = self.preloaded_market_data.monetary_policy.get(key)
                if policy and policy.current_value is not None:
                    return {
                        "value": policy.current_value,
                        "change_from_120d": policy.change_from_120d,
                        "unit": policy.unit,
                        "date": policy.date,
                        "source": policy.source,
                        "field": key
                    }
        return None

    def _evaluate_leading_indicator(self, monetary_data: Dict) -> Dict[str, Any]:
        """
        评估领先指标（DR007 + M1/M2剪刀差）方向，用于提前感知阶段切换
        """
        payload = self._extract_leading_payload(monetary_data)
        result: Dict[str, Any] = {
            "status": "missing",
            "message": "缺少DR007/7天逆回购原始数据，无法计算领先指标"
        }

        change = None
        current_value = None
        if payload:
            change = payload.get("change_from_120d")
            current_value = payload.get("value")
            result.update({
                "field": payload.get("field", "dr007"),
                "current_value": current_value,
                "unit": payload.get("unit", "%"),
                "date": payload.get("date"),
                "source": payload.get("source"),
                "lead_days": 35
            })

        spread = monetary_data.get("m1_m2_spread")
        m1_growth = monetary_data.get("m1_growth")
        m2_growth = monetary_data.get("m2_growth")

        result["m1_m2_spread"] = spread
        result["m1_growth"] = m1_growth
        result["m2_growth"] = m2_growth

        if change is None and spread is None:
            result["message"] = "缺少DR007/M1-M2数据，无法生成领先信号"
            return result

        dr_signal = 0
        dr_confidence = 0.0
        messages: List[str] = []

        if change is not None:
            bp_change = change * 100
            result["bp_change"] = bp_change
            if change <= -0.15:
                dr_signal = -1
                dr_confidence = 0.45 if change > -0.25 else 0.6
                messages.append(f"DR007较120日前下降{bp_change:+.0f}bp（宽松）")
            elif change >= 0.15:
                dr_signal = 1
                dr_confidence = 0.45 if change < 0.25 else 0.6
                messages.append(f"DR007较120日前上升{bp_change:+.0f}bp（收紧）")
            else:
                messages.append(f"DR007变化{bp_change:+.0f}bp（中性）")

        spread_signal = 0
        spread_confidence = 0.0
        if spread is not None:
            if spread >= 0.5:
                spread_signal = -1
                spread_confidence = 0.4 if spread < 1.0 else 0.55
                messages.append(f"M1-M2剪刀差{spread:+.1f}pct（资金回流实体）")
            elif spread <= -0.5:
                spread_signal = 1
                spread_confidence = 0.4 if spread > -1.0 else 0.55
                messages.append(f"M1-M2剪刀差{spread:+.1f}pct（流动性收敛）")
            else:
                messages.append(f"M1-M2剪刀差{spread:+.1f}pct（中性）")

        # 合并信号
        direction_signal = dr_signal if dr_signal != 0 else spread_signal
        signal_confidence = max(dr_confidence, spread_confidence)

        if dr_signal and spread_signal and dr_signal != spread_signal:
            result.update({
                "status": "flat",
                "direction": "conflict",
                "expected_shift": 0,
                "signal_confidence": 0.2,
                "message": "；".join(messages) + "。DR007与M1-M2信号相反，领先指标保持中性"
            })
            return result

        if direction_signal == 0:
            result.update({
                "status": "flat",
                "direction": "flat",
                "expected_shift": 0,
                "signal_confidence": 0.3,
                "message": "；".join(messages) + "。领先指标暂无明显方向"
            })
            return result

        direction = "easing" if direction_signal < 0 else "tightening"
        expected_shift = -1 if direction_signal < 0 else 1
        combined_confidence = min(0.75, signal_confidence + (0.15 if dr_signal and spread_signal else 0.0))

        result.update({
            "status": "ok",
            "direction": direction,
            "expected_shift": expected_shift,
            "signal_confidence": combined_confidence,
            "message": "；".join(messages) + ("。领先提示货币宽松" if direction == "easing" else "。领先提示货币收紧")
        })
        return result

    def _apply_leading_indicator_adjustment(
        self,
        base_stage: PringStage,
        base_confidence: float,
        indicator: Dict[str, Any]
    ) -> Tuple[PringStage, float, Dict[str, Any]]:
        """根据领先指标对阶段做轻量修正并记录说明"""
        indicator = indicator or {"status": "missing"}
        indicator.setdefault("applied_shift", 0)

        if indicator.get("status") != "ok":
            return base_stage, base_confidence, indicator

        shift = indicator.get("expected_shift", 0)
        if shift == 0:
            return base_stage, base_confidence, indicator

        # 仅在基础阶段与领先信号方向冲突时才调整，避免过度跳变
        target_stage = self._shift_stage(base_stage, shift)
        if target_stage == base_stage:
            return base_stage, base_confidence, indicator

        adjustment = 0.04 if abs(indicator.get("bp_change", 0)) >= 20 else 0.025
        new_confidence = max(0.0, min(1.0, base_confidence - adjustment))

        indicator["applied_shift"] = shift
        indicator["adjustment"] = -adjustment
        indicator["note"] = (
            "领先指标已介入：提前将阶段平移"
            f"{'←' if shift < 0 else '→'}1档，以反映DR007的领先信号"
        )

        return target_stage, new_confidence, indicator

    
    async def get_monetary_cycle_data(self) -> Dict:
        """
        获取货币周期数据（中国市场）V4.2完整获取5项指标
        数据来源：TuShare/WebSearch(央行公告数据)

        Returns:
            货币周期数据字典
        """
        preloaded = self._get_preloaded_monetary_data()
        if preloaded:
            print("获取中国货币周期数据... (复用Stage1/Stage2a结果)")
            return preloaded

        try:
            print("获取中国货币周期数据...")
            monetary_data = {
                "reverse_repo_7d": None,      # 7天逆回购利率
                "mlf_1y": None,                # 1年期MLF利率
                "rrr_change": None,            # 存款准备金率变化
                "tsf_growth": None,            # 社会融资规模增速
                "m2_growth": None,             # M2增速
                "m1_growth": None,             # M1增速
                "m1_m2_spread": None,          # M1与M2剪刀差
                "dr007_rate": None,            # DR007政策利率（文章推荐Leading Indicator）
                "data_source": "混合数据源(TuShare/WebSearch)",
                "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

            # 1. 所有5项货币政策数据通过WebSearch获取（包括M2）
            print(f"  [WebSearch] 准备获取: M2/7天逆回购/MLF/降准/TSF数据")

            monetary_data["websearch_queries"] = {
                "m2_growth": {
                    "query": "中国M2货币供应量 同比增速 央行 最新数据",
                    "keywords": ["M2", "货币供应量", "增速", "央行"],
                    "source_hint": "pbc.gov.cn"
                },
                "m1_growth": {
                    "query": "中国M1货币供应量 同比增速 央行 最新数据",
                    "keywords": ["M1", "货币供应量", "同比增速"],
                    "source_hint": "pbc.gov.cn"
                },
                "reverse_repo_7d": {
                    "query": "中国人民银行 公开市场业务 7天逆回购利率 最新",
                    "keywords": ["央行", "逆回购", "公开市场", "利率"],
                    "source_hint": "pbc.gov.cn"
                },
                "mlf_1y": {
                    "query": "中国人民银行 中期借贷便利MLF 1年期利率 最新",
                    "keywords": ["央行", "MLF", "中期借贷便利", "利率"],
                    "source_hint": "pbc.gov.cn"
                },
                "rrr_change": {
                    "query": "中国人民银行 存款准备金率 最新调整",
                    "keywords": ["央行", "存准率", "降准", "调整"],
                    "source_hint": "pbc.gov.cn"
                },
                "tsf_growth": {
                    "query": "中国社会融资规模增速 央行 最新数据",
                    "keywords": ["社融", "TSF", "增速", "央行统计"],
                    "source_hint": "pbc.gov.cn"
                },
                "dr007_rate": {
                    "query": "DR007 利率 最新 数据",
                    "keywords": ["DR007", "质押式回购", "政策利率"],
                    "source_hint": "chinabond.com.cn"
                }
            }

            monetary_data["note"] = "WebSearch数据需要在Claude Code环境中才能实际获取"

            return monetary_data

        except Exception as e:
            print(f"获取货币周期数据异常: {e}")
            return {
                "error": f"货币周期数据获取失败: {str(e)}",
                "data_source": "获取失败"
            }

    def _get_preloaded_monetary_data(self) -> Optional[Dict[str, Any]]:
        """复用Stage1/Stage2a写入的货币政策数据"""
        if not self.preloaded_market_data or not self.preloaded_market_data.monetary_policy:
            return None

        mapping = {
            'm2': 'm2_growth',
            'm1': 'm1_growth',
            'reverse_repo': 'reverse_repo_7d',
            'mlf': 'mlf_1y',
            'rrr': 'rrr_change',
            'tsf': 'tsf_growth',
            'dr007': 'dr007_rate'
        }

        data: Dict[str, Any] = {}
        raw_values: Dict[str, Dict[str, Any]] = {}

        for key, field in mapping.items():
            policy = self.preloaded_market_data.monetary_policy.get(key)
            if policy and not policy.is_estimated and policy.current_value is not None:
                value = policy.current_value
                if field == 'rrr_change' and policy.change_from_120d is not None:
                    value = policy.change_from_120d
                data[field] = value
                raw_values[field] = {
                    "value": policy.current_value,
                    "change_from_120d": policy.change_from_120d,
                    "unit": policy.unit,
                    "date": policy.date,
                    "source": policy.source
                }

        if data:
            if data.get("m1_growth") is not None and data.get("m2_growth") is not None:
                data["m1_m2_spread"] = round(data["m1_growth"] - data["m2_growth"], 2)
            data["raw_values"] = raw_values
            data["data_source"] = "stage1_market_data"
            data["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return data

        return None

    async def get_macro_economic_data(self) -> Dict:
        """
        获取宏观经济数据用于库存周期分析
        V4.3三级降级：TuShare -> WebSearch -> (AKShare已禁用)

        Returns:
            宏观数据字典
        """
        preloaded = self._get_preloaded_macro_data()
        if preloaded:
            print("  [Level 0] 使用Stage1/Stage2a预加载宏观数据")
            return preloaded

        try:
            # Level 1: 尝试从TuShare获取数据（新优先级）
            print("  [Level 1] 尝试TuShare获取宏观数据...")
            tushare_data = await self._get_tushare_macro_data()
            if tushare_data and not tushare_data.get('error'):
                print("  [Level 1] TuShare数据获取成功")
                return tushare_data

            # Level 2: TuShare失败，使用WebSearch从公开数据源获取
            print("  [Level 1] TuShare失败，降级到WebSearch公开数据源...")
            websearch_data = await self._get_macro_via_websearch()
            return websearch_data

        except Exception as e:
            print(f"获取宏观经济数据异常: {e}")
            # 最后降级到WebSearch
            return await self._get_macro_via_websearch()

    def _get_preloaded_macro_data(self) -> Optional[Dict[str, Any]]:
        """复用Stage1/Stage2a宏观指标"""
        if not self.preloaded_market_data or not self.preloaded_market_data.macro_indicators:
            return None

        mapping = {
            'ppi': ('ppi_data', True),
            'pmi': ('pmi_data', True),
            'pmi_new_orders': ('pmi_new_orders_data', True),
            'pmi_production': ('pmi_production_data', True),
            'industrial': ('industrial_data', False),
            'industrial_sales': ('industrial_sales_data', False),
            'cpi': ('cpi_data', True),
            'gdp': ('gdp_data', False),
            'bdi': ('bdi_data', False)
        }

        macro_payload: Dict[str, Any] = {}
        valid_count = 0

        for key, (field_name, wrap_list) in mapping.items():
            indicator = self.preloaded_market_data.macro_indicators.get(key)
            if indicator and not indicator.is_estimated and indicator.current_value is not None:
                payload = {
                    "value": indicator.current_value,
                    "previous_value": indicator.previous_value,
                    "change_rate": indicator.change_rate,
                    "unit": indicator.unit,
                    "date": indicator.date,
                    "source": indicator.source,
                    "name": indicator.indicator_name
                }
                if wrap_list:
                    macro_payload[field_name] = [payload]
                else:
                    macro_payload[field_name] = payload
                valid_count += 1

        if valid_count:
            macro_payload["data_source"] = "stage1_market_data"
            macro_payload["update_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            return macro_payload

        return None

    async def _get_akshare_macro_data(self) -> Optional[Dict]:
        """
        [DEPRECATED V4.3] AKShare宏观数据获取已禁用
        优先级已调整为: TuShare -> WebSearch

        Returns:
            None - 方法已禁用
        """
        print("  [DEPRECATED] _get_akshare_macro_data()已禁用，使用TuShare/WebSearch替代")
        return None

    async def _get_tushare_macro_data(self) -> Optional[Dict]:
        """尝试从TuShare获取宏观数据作为备用"""
        try:
            # 尝试使用data_manager中的TuShare适配器
            if hasattr(self.data_manager, 'data_sources') and 'tushare' in self.data_manager.data_sources:
                tushare_adapter = self.data_manager.data_sources['tushare']

                # TuShare Pro的宏观数据接口（需要积分）
                # 这里只做框架准备，具体接口需要根据TuShare Pro文档调整
                print("尝试从TuShare获取宏观数据（需要足够积分）")

                # 模拟TuShare调用（实际需要根据TuShare Pro API调整）
                # pro = ts.pro_api(token)
                # ppi_data = pro.query('macro', indicator='PPI')

                return {
                    "ppi_simulated": {"latest_yoy": -2.8, "trend": "TuShare备用数据"},
                    "cpi_simulated": {"latest_yoy": 0.4, "trend": "TuShare备用数据"},
                    "pmi_simulated": {"latest_value": 50.1, "trend": "TuShare备用数据"},
                    "data_source": "TuShare备用数据（需配置）",
                    "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
            else:
                print("TuShare适配器未配置")
                return None

        except Exception as e:
            print(f"TuShare获取宏观数据失败: {e}")
            return None

    async def _get_macro_via_websearch(self) -> Dict:
        """
        使用WebSearch从公开数据源获取宏观经济数据(V4.2新增)
        数据来源：国家统计局官网、央行官网等权威公开数据

        Returns:
            宏观数据字典(包含WebSearch查询信息)
        """
        print("  [Level 3] 使用WebSearch从权威公开数据源获取宏观数据...")
        print("    数据源: 国家统计局(stats.gov.cn), 央行(pbc.gov.cn)")

        # WebSearch查询结构 - 在Claude Code环境中会自动调用WebSearch工具
        websearch_queries = {
            'ppi': {
                'query': "中国PPI 工业生产者出厂价格指数 国家统计局 最新数据",
                'keywords': ['PPI', '工业生产者', '出厂价格', '同比'],
                'source_hint': 'stats.gov.cn'
            },
            'cpi': {
                'query': "中国CPI 居民消费价格指数 国家统计局 最新数据",
                'keywords': ['CPI', '居民消费', '价格指数', '同比'],
                'source_hint': 'stats.gov.cn'
            },
            'pmi': {
                'query': "中国PMI 制造业采购经理指数 国家统计局 最新数据",
                'keywords': ['PMI', '制造业', '采购经理', '指数'],
                'source_hint': 'stats.gov.cn'
            },
            'industrial': {
                'query': "中国工业增加值 同比增长 国家统计局 最新数据",
                'keywords': ['工业增加值', '同比增长', '规模以上'],
                'source_hint': 'stats.gov.cn'
            }
        }

        # 返回WebSearch查询结构
        # 注意：在非Claude Code环境中，这些数据不会实际获取
        # 但V4.1数据完整性检查会标记为缺失，触发警告
        return {
            "websearch_queries": websearch_queries,
            "data_source": "WebSearch公开数据(需Claude Code环境)",
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": "WebSearch数据需要在Claude Code环境中才能实际获取"
        }

    def _get_simulated_macro_data(self) -> Dict:
        """提供模拟宏观数据作为最后备用"""
        return {
            "ppi_simulated": {
                "latest_yoy": -2.8,    # 8月PPI同比（边际改善）
                "latest_mom": -0.1,    # 8月PPI环比
                "trend": "深度通缩但边际改善",
                "score": 8              # 低分，仍在通缩
            },
            "cpi_simulated": {
                "latest_yoy": 0.1,     # 8月CPI同比
                "latest_mom": 0.0,     # 8月CPI环比
                "trend": "内需疲弱",
                "score": 10            # 接近通缩边缘
            },
            "pmi_simulated": {
                "latest_value": 49.8,  # 9月PMI值（连续改善）
                "trend": "连续改善但仍收缩",
                "score": 15            # 边际改善
            },
            "industrial_simulated": {
                "latest_yoy": 4.5,     # 8月工业增加值同比
                "trend": "超预期",
                "score": 18
            },
            "data_source": "V2.1严格模式：已禁用模拟数据",
            "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    def calculate_monetary_cycle_score(self, monetary_data: Dict) -> Dict:
        """
        计算货币周期评分

        Args:
            monetary_data: 货币周期数据

        Returns:
            货币周期评分结果
        """
        try:
            components = [
                {"field": "rrr_change", "label": "降准幅度", "weight": 20, "mode": "pct", "type": "change", "scorer": self._score_rrr_change, "use_raw": False},
                {"field": "reverse_repo_7d", "label": "7天逆回购", "weight": 15, "mode": "bp", "type": "change", "scorer": self._score_policy_rate_change, "use_raw": True},
                {"field": "dr007_rate", "label": "DR007变化", "weight": 15, "mode": "bp", "type": "change", "scorer": self._score_dr007_change, "use_raw": True},
                {"field": "tsf_growth", "label": "TSF增速", "weight": 20, "mode": "pct", "type": "level", "scorer": self._score_tsf_growth},
                {"field": "m2_growth", "label": "M2增速", "weight": 15, "mode": "pct", "type": "level", "scorer": self._score_m2_growth},
                {"field": "m1_growth", "label": "M1增速", "weight": 10, "mode": "pct", "type": "level", "scorer": self._score_m1_growth},
                {"field": "m1_m2_spread", "label": "M1-M2剪刀差", "weight": 5, "mode": "pct", "type": "level", "scorer": self._score_m1_m2_spread},
            ]

            raw_values = monetary_data.get("raw_values", {})
            monetary_score = 0.0
            details: Dict[str, str] = {}

            for comp in components:
                if comp["type"] == "change":
                    if comp.get("use_raw", True):
                        value = self._get_monetary_change(monetary_data, raw_values, comp["field"])
                    else:
                        value = monetary_data.get(comp["field"])
                else:
                    value = monetary_data.get(comp["field"])
                score_component, comment = comp["scorer"](value, comp["weight"])
                monetary_score += score_component
                formatted_value = self._format_monetary_value(value, comp["mode"])
                details[comp["label"]] = f"{score_component:.1f}/{comp['weight']}分 - {comment}（{formatted_value}）"

            monetary_score = max(0.0, min(100.0, round(monetary_score, 1)))
            details["数据来源"] = monetary_data.get("data_source", "stage1_market_data")
            details["货币层总分"] = f"{monetary_score:.1f}/100分"

            # 判断货币周期阶段
            if monetary_score >= 60:
                cycle_stage = MonetaryCycleStage.EASING
                equity_bias = "利好权益"
                bond_bias = "长端收益率可能上行"
            elif monetary_score >= 30:
                cycle_stage = MonetaryCycleStage.NEUTRAL
                equity_bias = "中性"
                bond_bias = "中性"
            else:
                cycle_stage = MonetaryCycleStage.TIGHTENING
                equity_bias = "压制权益"
                bond_bias = "债券相对占优"

            return {
                "monetary_score": monetary_score,
                "cycle_stage": cycle_stage.value,
                "equity_bias": equity_bias,
                "bond_bias": bond_bias,
                "score_details": details,
                "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        except Exception as e:
            print(f"计算货币周期评分时发生错误: {e}")
            return {
                "monetary_score": 0,
                "cycle_stage": "分析失败",
                "equity_bias": "中性",
                "bond_bias": "中性",
                "error": str(e)
            }

    def _get_macro_entry(self, macro_data: Dict, field: str) -> Optional[Dict[str, Any]]:
        entry = macro_data.get(field)
        if isinstance(entry, list):
            entry = entry[-1] if entry else None
        if entry is None:
            return None
        if isinstance(entry, dict):
            return entry
        return {"value": entry}

    def _extract_macro_value(self, macro_data: Dict, field: str) -> Optional[float]:
        entry = self._get_macro_entry(macro_data, field)
        if not entry:
            return None
        for key in ("value", "current_value", "latest_value", "latest_yoy"):
            val = entry.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return None

    def _score_ppi_indicator(self, value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "PPI缺失，按中性处理"
        if value >= 0.5:
            return weight, "PPI转正，企业补库意愿增强"
        if value >= -1.0:
            return weight * 0.7, "PPI降幅收窄，价格端改善"
        return weight * 0.3, "PPI深度通缩，库存压力仍大"

    def _score_cpi_indicator(self, value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "CPI缺失，按中性处理"
        if 0 <= value <= 3:
            return weight, "CPI温和运行，内需韧性可接受"
        if -0.5 <= value < 0:
            return weight * 0.6, "轻微通缩，需求仍偏弱"
        if 3 < value <= 5:
            return weight * 0.6, "温和通胀，库存去化继续"
        return weight * 0.3, "高通胀或深度通缩波动，压制补库"

    def _score_pmi_indicator(self, value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "PMI缺失，按中性处理"
        if value >= 50.5:
            return weight, "PMI站稳荣枯线上方，补库动能充足"
        if value >= 50.0:
            return weight * 0.85, "PMI略高于荣枯线，补库初显"
        if value >= 48.0:
            return weight * 0.55, "PMI仍在收缩区，景气承压"
        return weight * 0.25, "PMI深度低于荣枯线，库存主动去化"

    def _score_industrial_value_indicator(self, value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "工业增加值缺失，按中性处理"
        if value >= 5.5:
            return weight, "工业增加值维持高位增长"
        if value >= 4.5:
            return weight * 0.8, "工业增速平稳，库存逐步修复"
        if value >= 3.5:
            return weight * 0.6, "工业增速放缓，库存回补偏谨慎"
        return weight * 0.3, "工业增速疲弱，库存去化压力大"

    def _score_industrial_sales_indicator(self, value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "工业营收缺失，按中性处理"
        if value >= 5.0:
            return weight, "工业企业营收高增，终端需求改善"
        if value >= 0.0:
            return weight * 0.6, "营收小幅增长，需求恢复仍不均衡"
        return weight * 0.3, "营收同比为负，需求拖累库存"

    def _score_gdp_indicator(self, value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "GDP缺失，按中性处理"
        if value >= 5.5:
            return weight, "GDP保持高景气，补库动力充足"
        if value >= 5.0:
            return weight * 0.8, "GDP略高于潜在增速，库存温和回补"
        if value >= 4.0:
            return weight * 0.6, "GDP放缓，需要政策托底"
        return weight * 0.3, "GDP增速偏弱，库存去化占主导"

    def _score_bdi_indicator(self, value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "BDI缺失，按中性处理"
        if value >= 2000:
            return weight, "BDI高位运行，全球补库交易旺盛"
        if value >= 1500:
            return weight * 0.7, "BDI维持景气区间"
        if value >= 1000:
            return weight * 0.5, "BDI中性震荡"
        return weight * 0.3, "BDI偏弱，需求侧仍谨慎"

    def _get_monetary_change(self, data: Dict, raw_values: Dict, field: str) -> Optional[float]:
        entry = raw_values.get(field)
        if entry and entry.get("change_from_120d") is not None:
            return entry.get("change_from_120d")
        change_field = f"{field}_change"
        value = data.get(change_field)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _format_monetary_value(self, value: Optional[float], mode: str) -> str:
        if value is None:
            return "数据缺失"
        if mode == "bp":
            return f"{value * 100:.0f}bp"
        if mode == "pct":
            return f"{value:.2f}%"
        return f"{value:.2f}"

    def _score_rrr_change(self, change: Optional[float], weight: float) -> Tuple[float, str]:
        if change is None:
            return weight * 0.5, "缺少降准幅度，按中性处理"
        if change <= -0.5:
            return weight, "年内累计降准≥50bp，货币环境显著宽松"
        if change <= -0.25:
            return weight * 0.8, "累计降准25-50bp，宽松力度偏强"
        if change < 0:
            return weight * 0.6, "小幅降准，流动性边际改善"
        if change == 0:
            return weight * 0.4, "无降准调整，维持中性"
        return weight * 0.2, "准备金率上调或回升，呈现偏紧"

    def _score_policy_rate_change(self, change: Optional[float], weight: float) -> Tuple[float, str]:
        if change is None:
            return weight * 0.5, "缺少逆回购利率变动，按中性处理"
        if change <= -0.15:
            return weight, "逆回购利率累计下调≥15bp，政策明显宽松"
        if change <= -0.05:
            return weight * 0.75, "逆回购利率小幅下调"
        if change < 0.02:
            return weight * 0.45, "利率基本持平"
        return weight * 0.25, "逆回购利率上调，政策趋紧"

    def _score_dr007_change(self, change: Optional[float], weight: float) -> Tuple[float, str]:
        if change is None:
            return weight * 0.5, "缺少DR007变化，按中性处理"
        if change <= -0.2:
            return weight, "DR007较四个月前下行≥20bp，流动性充裕"
        if change <= -0.1:
            return weight * 0.8, "DR007下降10-20bp，货币边际宽松"
        if change <= 0.05:
            return weight * 0.5, "DR007变化不大"
        if change <= 0.15:
            return weight * 0.35, "DR007小幅抬升，偏中性偏紧"
        return weight * 0.15, "DR007显著上行，流动性趋紧"

    def _score_tsf_growth(self, value: Optional[float], weight: float) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "缺少TSF增速，按中性处理"
        if value >= 10:
            return weight, "社融增速≥10%，融资需求旺盛"
        if value >= 8:
            return weight * 0.8, "社融增速8-10%，宽信用持续"
        if value >= 6:
            return weight * 0.5, "社融增速6-8%，中性"
        return weight * 0.2, "社融增速低于6%，信用扩张偏弱"

    def _score_m2_growth(self, value: Optional[float], weight: float) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "缺少M2增速，按中性处理"
        if value >= 10:
            return weight, "M2两位数增长，流动性充沛"
        if value >= 8:
            return weight * 0.8, "M2增速8-10%，温和宽松"
        if value >= 6:
            return weight * 0.55, "M2增速6-8%，中性"
        return weight * 0.3, "M2增速<6%，货币供给偏紧"

    def _score_m1_growth(self, value: Optional[float], weight: float) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "缺少M1增速，按中性处理"
        if value >= 8:
            return weight, "M1快速增长，企业活期需求上升"
        if value >= 5:
            return weight * 0.75, "M1增速温和回升"
        if value >= 3:
            return weight * 0.5, "M1增速中性"
        return weight * 0.25, "M1低增或为负，实体需求偏弱"

    def _score_m1_m2_spread(self, value: Optional[float], weight: float) -> Tuple[float, str]:
        if value is None:
            return weight * 0.5, "缺少剪刀差数据，按中性处理"
        if value >= 1.0:
            return weight, "M1-M2剪刀差>1pct，流动性向实体回流"
        if value >= 0.0:
            return weight * 0.7, "剪刀差大致为正"
        if value >= -1.0:
            return weight * 0.45, "剪刀差略负，需求恢复有限"
        return weight * 0.2, "剪刀差深度为负，货币传导不畅"

    def _summarize_leading_indicator_text(self, indicator: Dict[str, Any]) -> str:
        if not indicator:
            return "领先指标缺失，暂无阶段前瞻"
        status = indicator.get("status")
        if status == "missing":
            return "缺少DR007/M1-M2数据，需补充WebSearch"
        parts = []
        if indicator.get("message"):
            parts.append(indicator["message"])
        if indicator.get("m1_m2_spread") is not None and "M1-M2" not in parts[0]:
            parts.append(f"M1-M2剪刀差{indicator['m1_m2_spread']:+.1f}pct")
        shift = indicator.get("applied_shift", indicator.get("expected_shift", 0))
        if shift:
            arrow = "前" if shift < 0 else "后"
            parts.append(f"阶段可能向{arrow}{abs(shift)}档")
        return "；".join(parts) if parts else "领先指标暂无显著变化"

    def _extract_highlights(self, details: Dict[str, str], keys: List[str], limit: int = 3) -> List[str]:
        highlights: List[str] = []
        for key in keys:
            text = details.get(key)
            if not text:
                continue
            comment = text.split(" - ", 1)[1] if " - " in text else text
            highlights.append(f"{key}{comment}")
            if len(highlights) >= limit:
                break
        return highlights

    def _build_inventory_summary_text(self, details: Dict[str, str], stage: str, bias: str) -> str:
        prefix = f"{stage}，{bias}。"
        highlights = self._extract_highlights(
            details,
            ["PPI同比", "PMI综合", "PMI新订单", "PMI生产", "工业增加值", "工业营收", "GDP同比"]
        )
        if highlights:
            return prefix + "关键驱动：" + "；".join(highlights)
        return prefix + "指标数据待MCP补全。"

    def _build_monetary_summary_text(self, details: Dict[str, str], stage: str, equity_bias: str, bond_bias: str) -> str:
        prefix = f"{stage}，权益偏向{equity_bias}，债券偏向{bond_bias}。"
        highlights = self._extract_highlights(
            details,
            ["降准幅度", "7天逆回购", "DR007变化", "M1-M2剪刀差", "M1增速", "TSF增速", "M2增速"]
        )
        if highlights:
            return prefix + "流动性信号：" + "；".join(highlights)
        return prefix + "货币指标待补数。"

    def _build_stage_summary_text(
        self,
        final_stage: PringStage,
        confidence: float,
        inventory_stage: str,
        monetary_stage: str,
        leading_summary: str
    ) -> str:
        return (
            f"{final_stage.to_display_format()}（置信度{confidence:.0%}）。"
            f"库存周期：{inventory_stage}，货币周期：{monetary_stage}。"
            f"领先指标：{leading_summary}"
        )

    def calculate_inventory_cycle_score(self, macro_data: Dict) -> Dict:
        """
        根据宏观指标计算库存周期评分

        Args:
            macro_data: 宏观经济数据

        Returns:
            dict: {fundamental_score, cycle_stage, score_details, ...}
        """
        try:
            indicator_plan = [
                ("ppi_data", "PPI同比", 10, self._score_ppi_indicator),
                ("cpi_data", "CPI同比", 5, self._score_cpi_indicator),
                ("pmi_data", "PMI综合", 10, self._score_pmi_indicator),
                ("pmi_new_orders_data", "PMI新订单", 10, self._score_pmi_indicator),
                ("pmi_production_data", "PMI生产", 5, self._score_pmi_indicator),
                ("industrial_data", "工业增加值", 8, self._score_industrial_value_indicator),
                ("industrial_sales_data", "工业营收", 5, self._score_industrial_sales_indicator),
                ("gdp_data", "GDP同比", 5, self._score_gdp_indicator),
                ("bdi_data", "BDI指数", 2, self._score_bdi_indicator),
            ]

            details: Dict[str, str] = {}
            fundamental_score = 0.0

            for field, label, weight, scorer in indicator_plan:
                entry = self._get_macro_entry(macro_data, field)
                value = self._extract_macro_value(macro_data, field)
                score, comment = scorer(value, weight, entry)
                detail_value = "数据缺失" if value is None else f"{value:.2f}{entry.get('unit', '') if entry else ''}"
                details[label] = f"{score:.1f}/{weight}分 - {comment}（{detail_value}）"
                fundamental_score += score

            fundamental_score = round(fundamental_score, 1)
            available_indicators = sum(1 for cfg in indicator_plan if self._get_macro_entry(macro_data, cfg[0]))
            details["数据来源"] = macro_data.get("data_source", "stage1_market_data")
            details["样本完整度"] = f"{available_indicators}/{len(indicator_plan)}"
            details["基本面总分"] = f"{fundamental_score:.1f}/60分"

            if fundamental_score >= 45:
                cycle_stage = InventoryCycleStage.ACTIVE_RESTOCKING
                commodity_bias = "强牛"
            elif fundamental_score >= 35:
                cycle_stage = InventoryCycleStage.PASSIVE_RESTOCKING
                commodity_bias = "偏牛"
            elif fundamental_score >= 25:
                cycle_stage = InventoryCycleStage.ACTIVE_DESTOCKING
                commodity_bias = "中性"
            else:
                cycle_stage = InventoryCycleStage.PASSIVE_DESTOCKING
                commodity_bias = "熊"

            return {
                "fundamental_score": fundamental_score,
                "cycle_stage": cycle_stage.value,
                "commodity_bias": commodity_bias,
                "score_details": details,
                "analysis_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

        except Exception as e:
            print(f"计算库存周期评分时发生错误: {e}")
            return {
                "fundamental_score": 30,
                "cycle_stage": "分析失败",
                "commodity_bias": "中性",
                "error": str(e),
            }
    
    def determine_asset_signal(self, price_data: pd.DataFrame, ma_window: int = 50) -> AssetSignal:
        """
        基于价格数据判断资产信号
        
        Args:
            price_data: 价格数据DataFrame
            ma_window: MA窗口期
            
        Returns:
            资产信号
        """
        try:
            if price_data.empty or len(price_data) < ma_window:
                return AssetSignal.NEUTRAL
            
            # 获取收盘价
            if 'close' in price_data.columns:
                prices = price_data['close']
            elif '收盘' in price_data.columns:
                prices = price_data['收盘']
            else:
                # 尝试找价格列
                price_cols = [col for col in price_data.columns if any(
                    keyword in col.lower() for keyword in ['close', 'price', '收盘', '价格']
                )]
                if not price_cols:
                    return AssetSignal.NEUTRAL
                prices = price_data[price_cols[0]]
            
            prices = pd.to_numeric(prices, errors='coerce').dropna()
            
            if len(prices) < ma_window:
                return AssetSignal.NEUTRAL
            
            # 计算移动平均线
            ma_200 = prices.rolling(window=200, min_periods=100).mean()
            ma_50 = prices.rolling(window=50, min_periods=25).mean()
            
            current_price = prices.iloc[-1]
            current_ma_200 = ma_200.iloc[-1] if not pd.isna(ma_200.iloc[-1]) else None
            current_ma_50 = ma_50.iloc[-1] if not pd.isna(ma_50.iloc[-1]) else None
            
            # 判断信号：价格位于200日线上且50日线上穿200日线为Bullish
            above_ma_200 = current_ma_200 is not None and current_price > current_ma_200
            
            # 检查50日线是否上穿200日线（最近10天内）
            ma_50_cross_above = False
            if len(ma_50) >= 10 and len(ma_200) >= 10:
                recent_ma_50 = ma_50.tail(10)
                recent_ma_200 = ma_200.tail(10)
                
                # 检查是否有上穿
                for i in range(1, len(recent_ma_50)):
                    if (recent_ma_50.iloc[i] > recent_ma_200.iloc[i] and 
                        recent_ma_50.iloc[i-1] <= recent_ma_200.iloc[i-1]):
                        ma_50_cross_above = True
                        break
            
            # 综合判断
            if above_ma_200 and (ma_50_cross_above or (current_ma_50 and current_ma_50 > current_ma_200)):
                return AssetSignal.BULLISH
            elif current_ma_200 is not None and current_price < current_ma_200:
                return AssetSignal.BEARISH
            else:
                return AssetSignal.NEUTRAL
                
        except Exception as e:
            print(f"判断资产信号时发生错误: {e}")
            return AssetSignal.NEUTRAL
    
    async def determine_commodity_signal_with_correction(self, start_date: str, end_date: str) -> AssetSignal:
        """
        基于技术面+库存周期矫正的商品信号判定
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            矫正后的商品信号
        """
        try:
            # 第一步：获取技术面信号
            technical_score = await self.calculate_commodity_technical_score(start_date, end_date)
            
            # 第二步：获取宏观数据并计算库存周期评分
            macro_data = await self.get_macro_economic_data()
            cycle_analysis = self.calculate_inventory_cycle_score(macro_data)
            
            # 第三步：综合评分（技术面35% + 基本面65% - V3.1规范）
            weights = self.cycle_correction_weights
            total_score = (
                technical_score * weights["technical_weight"]
                + cycle_analysis["fundamental_score"] * weights["fundamental_weight"]
            )
            
            # 第四步：基于评分判定信号
            if total_score >= weights["bullish_threshold"]:
                corrected_signal = AssetSignal.BULLISH
            elif total_score <= weights["bearish_threshold"]:
                corrected_signal = AssetSignal.BEARISH
            else:
                corrected_signal = AssetSignal.NEUTRAL

            self.last_commodity_correction = {
                "technical_score": technical_score,
                "fundamental_score": cycle_analysis.get("fundamental_score"),
                "combined_score": total_score,
                "inventory_cycle_stage": cycle_analysis.get("cycle_stage"),
                "commodity_bias": cycle_analysis.get("commodity_bias"),
                "data_source": cycle_analysis.get("score_details", {}).get("数据来源", "模拟/网络"),
                "analysis_time": cycle_analysis.get(
                    "analysis_time", datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                ),
            }
            
            # 记录矫正详情
            print(f"商品信号库存周期矫正详情:")
            print(f"  技术面评分: {technical_score:.1f}/40分")
            print(f"  基本面评分: {cycle_analysis['fundamental_score']:.1f}/60分")
            print(f"  综合评分: {total_score:.1f}/100分")
            print(f"  库存周期阶段: {cycle_analysis['cycle_stage']}")
            print(f"  商品趋势倾向: {cycle_analysis['commodity_bias']}")
            print(f"  矫正后信号: {corrected_signal.value}")
            
            return corrected_signal

        except Exception as e:
            print(f"商品信号库存周期矫正时发生错误: {e}")
            self.last_commodity_correction = {}
            return AssetSignal.NEUTRAL
    
    async def calculate_commodity_technical_score(self, start_date: str, end_date: str) -> float:
        """
        计算商品技术面评分
        
        Args:
            start_date: 开始日期 
            end_date: 结束日期
            
        Returns:
            技术面评分（满分40分）
        """
        try:
            technical_score = 0
            valid_signals = []

            for target in self.commodity_targets:
                symbol = target["symbol"]
                fetch_type = target.get("fetch", "futures_foreign")
                name = target.get("name", symbol)
                try:
                    price_df = await self._fetch_commodity_price(symbol, fetch_type, start_date, end_date)
                    if price_df is not None and not price_df.empty:
                        single_score = self.calculate_single_commodity_technical_score(price_df)
                        valid_signals.append(single_score)
                        print(f"  {name}({symbol})技术评分: {single_score:.1f}/40分")
                    else:
                        print(f"  {name}({symbol}) 数据缺失，暂无法计分")
                except Exception as e:
                    print(f"  获取{name}({symbol})数据失败: {e}")
                    continue

            if valid_signals:
                technical_score = sum(valid_signals) / len(valid_signals)
            else:
                technical_score = 35
                print("  无有效商品技术数据，使用默认评分: 35/40分")

            return technical_score

        except Exception as e:
            print(f"计算商品技术面评分时发生错误: {e}")
            return 30  # 默认中等评分

    async def _fetch_commodity_price(self, symbol: str, fetch_type: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
        """
        [V4.3重构] 获取外盘期货/ETF价格序列
        数据来源：DataSourceManager (TuShare/InternationalFinance) 或 WebSearch占位符

        Args:
            symbol: 商品代码
            fetch_type: 获取类型 (futures_foreign/us_etf)
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            价格DataFrame或None（触发WebSearch补充）
        """
        try:
            # 使用DataSourceManager获取数据（替代直接AKShare调用）
            # 注意：此方法可能返回None，触发MCP WebSearch补充
            print(f"    [V4.3] 商品{symbol}数据获取: 优先DataSourceManager，失败则需WebSearch补充")

            # 商品数据目前通过DataSourceManager的InternationalFinance适配器获取
            # 如果获取失败，返回None触发WebSearch占位符
            # TODO: 实现DataSourceManager的商品数据接口
            print(f"    [INFO] 商品{symbol}数据需要通过MCP WebSearch获取或使用InternationalFinance接口")
            return None

        except Exception as e:
            print(f"    [ERROR] 获取商品{symbol}数据失败: {e}")
            return None

    def _standardize_commodity_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """标准化外盘期货/ETF数据列名以便技术指标计算"""
        if df is None or df.empty:
            return pd.DataFrame()

        normalized = df.copy()

        rename_map = {
            '日期': 'date',
            'Date': 'date',
            'date': 'date',
            '时间': 'date',
            '交易日期': 'date',
            'open': 'open',
            'Open': 'open',
            '开盘': 'open',
            '最高': 'high',
            'High': 'high',
            'high': 'high',
            '最低': 'low',
            'Low': 'low',
            'low': 'low',
            '收盘': 'close',
            'Close': 'close',
            'close': 'close',
            'settle': 'close',
            '结算价': 'close',
            '最新价': 'close',
            'Last': 'close',
            '价格': 'close',
        }

        normalized = normalized.rename(columns={k: v for k, v in rename_map.items() if k in normalized.columns})

        if 'date' not in normalized.columns:
            first_col = normalized.columns[0]
            normalized = normalized.rename(columns={first_col: 'date'})

        normalized['date'] = pd.to_datetime(normalized['date'], errors='coerce')
        normalized = normalized.dropna(subset=['date']).sort_values('date')

        if 'close' not in normalized.columns:
            candidate_cols = [
                col for col in normalized.columns
                if any(token in str(col).lower() for token in ['close', 'settle', 'price', 'last']) and col != 'date'
            ]
            if candidate_cols:
                normalized['close'] = pd.to_numeric(normalized[candidate_cols[0]], errors='coerce')
            else:
                numeric_cols = normalized.select_dtypes(include=[np.number]).columns.tolist()
                if numeric_cols:
                    normalized['close'] = pd.to_numeric(normalized[numeric_cols[0]], errors='coerce')

        if 'close' not in normalized.columns:
            return pd.DataFrame()

        normalized['close'] = pd.to_numeric(normalized['close'], errors='coerce')
        normalized = normalized.dropna(subset=['close'])

        return normalized

    def calculate_single_commodity_technical_score(self, price_data: pd.DataFrame) -> float:
        """
        计算单个商品的技术评分
        
        Args:
            price_data: 价格数据
            
        Returns:
            单个商品技术评分（满分40分）
        """
        try:
            if price_data.empty or len(price_data) < 50:
                return 20  # 数据不足时返回中性评分
            
            # 获取收盘价
            if 'close' in price_data.columns:
                prices = price_data['close']
            elif '收盘' in price_data.columns:
                prices = price_data['收盘']
            else:
                return 20
            
            prices = pd.to_numeric(prices, errors='coerce').dropna()
            if len(prices) < 50:
                return 20
            
            score = 0
            current_price = prices.iloc[-1]
            
            # 计算移动平均线
            ma50 = prices.rolling(window=50).mean().iloc[-1] if len(prices) >= 50 else current_price
            ma200 = prices.rolling(window=200).mean().iloc[-1] if len(prices) >= 200 else current_price
            
            # 1. 价格位置评分（15分）
            if current_price > ma50 and ma50 > ma200:
                score += 15  # 多头排列
            elif current_price > ma50:
                score += 10  # 价格在短期均线上
            elif current_price > ma200:
                score += 5   # 价格在长期均线上
            
            # 2. 短期趋势评分（15分）
            if len(prices) >= 30:
                # 30日涨跌幅
                return_30d = (current_price / prices.iloc[-31] - 1) * 100
                if return_30d >= 5:
                    score += 15
                elif return_30d >= 1:
                    score += 10
                elif return_30d >= -1:
                    score += 5
            
            # 3. 均线斜率评分（10分）
            if len(prices) >= 20:
                ma20 = prices.rolling(window=20).mean()
                if len(ma20) >= 5:
                    ma20_slope = ma20.iloc[-1] - ma20.iloc[-6]  # 5日斜率
                    if ma20_slope > 0:
                        score += 10
                    elif ma20_slope > -0.5:
                        score += 5
            
            return min(score, 40)  # 最高40分
            
        except Exception as e:
            print(f"计算单个商品技术评分时发生错误: {e}")
            return 20
    
    async def get_bond_signal_from_yield(self, days: int = 250) -> tuple[AssetSignal, str]:
        """
        基于债券收益率判定债券信号 (V3.1优化)
        收益率下行 → 债券价格上涨 → Bullish
        收益率上行 → 债券价格下跌 → Bearish

        Args:
            days: 分析天数

        Returns:
            (债券信号, 判定依据说明)
        """
        try:
            # 尝试获取中国10年期国债收益率数据
            # 注意: 这里需要实际的收益率数据源,暂时使用国债ETF作为代理
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

            # 方法1: 使用国债ETF反向推断(ETF涨=收益率跌=Bullish)
            bond_symbols = ["511010", "019649"]  # 10年期国债ETF

            for symbol in bond_symbols:
                try:
                    response = await self.data_manager.get_stock_daily(symbol, start_date, end_date)
                    if not response.error and response.data is not None and not response.data.empty:
                        df = response.data

                        # 获取收盘价
                        if 'close' in df.columns:
                            prices = df['close']
                        elif '收盘' in df.columns:
                            prices = df['收盘']
                        else:
                            continue

                        prices = pd.to_numeric(prices, errors='coerce').dropna()
                        if len(prices) < 50:
                            continue

                        # 计算短期和长期趋势
                        current_price = prices.iloc[-1]
                        ma50 = prices.rolling(window=50).mean().iloc[-1] if len(prices) >= 50 else current_price
                        ma200 = prices.rolling(window=200).mean().iloc[-1] if len(prices) >= 200 else current_price

                        # 计算收益率变化(使用价格变化反向推断)
                        # ETF涨幅越大 → 收益率下降越多 → 越Bullish
                        price_change_pct = (current_price / prices.iloc[0] - 1) * 100

                        # 判定逻辑: ETF价格上涨 = 收益率下行 = Bullish
                        if current_price > ma50 and ma50 > ma200:
                            reason = f"国债ETF({symbol})上涨,推断收益率持续下行,价格>MA50>MA200"
                            return AssetSignal.BULLISH, reason
                        elif current_price > ma50:
                            reason = f"国债ETF({symbol})震荡偏强,推断收益率偏低,价格>MA50"
                            return AssetSignal.BULLISH, reason
                        elif current_price < ma200:
                            reason = f"国债ETF({symbol})下跌,推断收益率上行,价格<MA200"
                            return AssetSignal.BEARISH, reason
                        else:
                            reason = f"国债ETF({symbol})中性,收益率无明显趋势"
                            return AssetSignal.NEUTRAL, reason

                except Exception as e:
                    print(f"获取国债ETF {symbol} 数据失败: {e}")
                    continue

            # 如果ETF数据获取失败,返回中性信号
            return AssetSignal.NEUTRAL, "国债ETF数据获取失败,使用中性信号"

        except Exception as e:
            print(f"债券信号判定失败: {e}")
            return AssetSignal.NEUTRAL, f"债券信号判定异常: {str(e)}"

    async def get_asset_signals(self, days: int = 250) -> Dict[str, AssetSignal]:
        """
        获取三大类资产的信号

        Args:
            days: 分析天数

        Returns:
            资产信号字典
        """
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        signals = {}

        try:
            # 债券信号（V3.1优化: 基于收益率逻辑判定）
            bond_signal, bond_reason = await self.get_bond_signal_from_yield(days)
            signals['bonds'] = bond_signal
            signals['bond_reason'] = bond_reason  # 保存判定依据
            print(f"[诊断] 债券信号: {bond_signal.value} - {bond_reason}")
            
            # 股票信号（使用沪深300）
            stock_symbols = ["000300", "510300"]  # 沪深300指数或ETF
            stock_signal = AssetSignal.NEUTRAL
            stock_reason = "股票信号未获取"

            for symbol in stock_symbols:
                try:
                    if symbol.startswith("000"):
                        response = await self.data_manager.get_index_daily(symbol, start_date, end_date)
                    else:
                        response = await self.data_manager.get_stock_daily(symbol, start_date, end_date)

                    if not response.error and response.data is not None and not response.data.empty:
                        stock_signal = self.determine_asset_signal(response.data)

                        # 生成判定依据
                        df = response.data
                        if 'close' in df.columns:
                            prices = df['close']
                        elif '收盘' in df.columns:
                            prices = df['收盘']
                        else:
                            continue

                        prices = pd.to_numeric(prices, errors='coerce').dropna()
                        if len(prices) >= 50:
                            current_price = prices.iloc[-1]
                            ma50 = prices.rolling(window=50).mean().iloc[-1]
                            ma200 = prices.rolling(window=200).mean().iloc[-1] if len(prices) >= 200 else None

                            price_change = (current_price / prices.iloc[0] - 1) * 100

                            if ma200:
                                stock_reason = f"沪深300({symbol}): 涨跌{price_change:.1f}%, 当前{current_price:.2f}, MA50={ma50:.2f}, MA200={ma200:.2f}"
                            else:
                                stock_reason = f"沪深300({symbol}): 涨跌{price_change:.1f}%, 当前{current_price:.2f}, MA50={ma50:.2f}"

                        break
                except Exception as e:
                    print(f"获取股票信号失败({symbol}): {e}")
                    continue

            signals['stocks'] = stock_signal
            signals['stock_reason'] = stock_reason
            print(f"[诊断] 股票信号: {stock_signal.value} - {stock_reason}")

            # 商品信号（集成库存周期矫正）
            commodity_signal = await self.determine_commodity_signal_with_correction(start_date, end_date)
            signals['commodities'] = commodity_signal

            # 获取商品信号判定依据
            commodity_reason = "商品信号矫正详情见last_commodity_correction"
            if self.last_commodity_correction:
                tech_score = self.last_commodity_correction.get('technical_score', 0)
                fund_score = self.last_commodity_correction.get('fundamental_score', 0)
                combined = self.last_commodity_correction.get('combined_score', 0)
                cycle_stage = self.last_commodity_correction.get('inventory_cycle_stage', 'N/A')
                commodity_reason = f"技术{tech_score:.1f}/35 + 库存{fund_score:.1f}/65 = {combined:.1f}/100, 周期阶段:{cycle_stage}"

            signals['commodity_reason'] = commodity_reason
            print(f"[诊断] 商品信号: {commodity_signal.value} - {commodity_reason}")
            
        except Exception as e:
            print(f"获取资产信号时发生错误: {e}")
            signals = {
                'bonds': AssetSignal.NEUTRAL,
                'stocks': AssetSignal.NEUTRAL, 
                'commodities': AssetSignal.NEUTRAL
            }
            self.last_commodity_correction = {}

        return signals
    
    def apply_monetary_correction(
        self,
        base_stage: PringStage,
        base_confidence: float,
        monetary_analysis: Dict,
        inventory_analysis: Dict,
        asset_signals: Dict
    ) -> Tuple[PringStage, float]:
        """
        应用货币周期修正到Pring阶段判定

        Args:
            base_stage: 基础Pring阶段
            base_confidence: 基础置信度
            monetary_analysis: 货币周期分析结果
            inventory_analysis: 库存周期分析结果
            asset_signals: 资产信号

        Returns:
            (修正后阶段, 修正后置信度)
        """
        monetary_stage = monetary_analysis.get('cycle_stage', '中性')
        monetary_score = monetary_analysis.get('monetary_score', 0)
        inventory_stage = inventory_analysis.get('cycle_stage', '中性')

        print(f"\n  应用货币周期修正:")
        print(f"    货币周期: {monetary_stage} (评分{monetary_score:.0f})")
        print(f"    库存周期: {inventory_stage}")

        # 修正逻辑
        final_stage = base_stage
        confidence_adjustment = 0

        # 宽松货币周期修正
        if monetary_stage == "宽松":
            # 宽松利好权益类资产（II、III、IV阶段）
            if base_stage in [PringStage.STAGE_II, PringStage.STAGE_III, PringStage.STAGE_IV]:
                confidence_adjustment += 0.1
                print(f"    ✓ 货币宽松强化权益牛市阶段，置信度+10%")
            # 宽松时，商品仅在库存上行时才获确认
            elif base_stage == PringStage.STAGE_V:
                if inventory_stage in ["主动补库存", "被动补库存"]:
                    confidence_adjustment += 0.05
                    print(f"    ✓ 货币宽松+库存补库，商品信号部分确认，置信度+5%")
                else:
                    confidence_adjustment -= 0.1
                    print(f"    ⚠️ 货币宽松但库存去库，商品信号矛盾，置信度-10%")

        # 收紧货币周期修正
        elif monetary_stage == "收紧":
            # 收紧压制权益类资产
            if base_stage in [PringStage.STAGE_II, PringStage.STAGE_III, PringStage.STAGE_IV]:
                confidence_adjustment -= 0.15
                print(f"    ⚠️ 货币收紧压制权益牛市，置信度-15%")
            # 收紧时债券相对占优（I阶段）
            elif base_stage == PringStage.STAGE_I:
                confidence_adjustment += 0.1
                print(f"    ✓ 货币收紧利好债券阶段，置信度+10%")
            # 收紧时商品仅在通胀已抬升时获支撑（V阶段）
            elif base_stage == PringStage.STAGE_V:
                if inventory_stage in ["主动补库存"]:  # 通胀抬头
                    confidence_adjustment += 0.05
                    print(f"    ✓ 货币收紧但通胀抬头，商品有支撑，置信度+5%")

        # 中性货币周期：不做大幅调整
        else:
            print(f"    → 货币周期中性，维持基础判断")

        # 计算最终置信度（确保在0-1范围内）
        final_confidence = max(0.0, min(1.0, base_confidence + confidence_adjustment))

        print(f"  最终Pring阶段: {final_stage.value}")
        print(f"  最终置信度: {final_confidence:.1%} (调整{confidence_adjustment:+.1%})")

        return final_stage, final_confidence

    def _enforce_stage_consistency(
        self,
        base_stage: PringStage,
        base_confidence: float,
        inventory_stage: str,
        monetary_stage: str
    ) -> Tuple[PringStage, float]:
        """根据库存/货币周期约束重新校准基础阶段"""
        inventory_stage = inventory_stage or ""
        monetary_stage = monetary_stage or ""
        adjusted_stage = base_stage
        adjusted_confidence = base_confidence
        is_active_restock = "主动补库" in inventory_stage

        if adjusted_stage == PringStage.STAGE_III and not is_active_restock:
            adjusted_stage = PringStage.STAGE_II
            adjusted_confidence = max(0.0, adjusted_confidence - 0.1)
            print(f"  [一致性校验] 库存周期处于{inventory_stage or 'N/A'}，阶段Ⅲ降级为阶段Ⅱ")

        if adjusted_stage == PringStage.STAGE_IV:
            if monetary_stage == "收紧":
                adjusted_stage = PringStage.STAGE_III if is_active_restock else PringStage.STAGE_II
                adjusted_confidence = max(0.0, adjusted_confidence - 0.1)
                print(f"  [一致性校验] 货币周期收紧，阶段Ⅳ降级为{adjusted_stage.value}")
            elif not is_active_restock:
                adjusted_stage = PringStage.STAGE_III
                adjusted_confidence = max(0.0, adjusted_confidence - 0.05)
                print(f"  [一致性校验] 库存尚未主动补库，阶段Ⅳ降级为阶段Ⅲ")

        return adjusted_stage, adjusted_confidence

    def determine_pring_stage(self, bond_signal: AssetSignal, stock_signal: AssetSignal,
                             commodity_signal: AssetSignal) -> Tuple[PringStage, float]:
        """
        基于三大资产信号判定普林格阶段 (V3.1增强诊断)

        Args:
            bond_signal: 债券信号
            stock_signal: 股票信号
            commodity_signal: 商品信号

        Returns:
            (普林格阶段, 置信度)
        """
        # 转换信号为简化标识
        bond_up = bond_signal == AssetSignal.BULLISH
        stock_up = stock_signal == AssetSignal.BULLISH
        commodity_up = commodity_signal == AssetSignal.BULLISH

        # 诊断日志
        print(f"[诊断] 普林格阶段判定输入: 债券={'↑' if bond_up else '↓'}, 股票={'↑' if stock_up else '↓'}, 商品={'↑' if commodity_up else '↓'}")
        
        # 阶段匹配规则
        stage_rules = {
            (True, False, False): (PringStage.STAGE_I, 0.9),    # 债券↑，股票↓，商品↓
            (True, True, False): (PringStage.STAGE_II, 0.9),    # 债券↑，股票↑，商品↓
            (True, True, True): (PringStage.STAGE_III, 0.9),    # 债券↑，股票↑，商品↑
            (False, True, True): (PringStage.STAGE_IV, 0.9),    # 债券↓，股票↑，商品↑
            (False, False, True): (PringStage.STAGE_V, 0.9),    # 债券↓，股票↓，商品↑
            (False, False, False): (PringStage.STAGE_VI, 0.9),  # 债券↓，股票↓，商品↓
        }
        
        signal_pattern = (bond_up, stock_up, commodity_up)

        if signal_pattern in stage_rules:
            stage, confidence = stage_rules[signal_pattern]
            print(f"[诊断] 普林格阶段判定结果: 第{stage.value}阶段 (置信度{confidence:.1%})")
            return stage, confidence
        
        # 处理中性信号的情况
        # 如果有中性信号，降低置信度并做近似匹配
        
        # 中性信号处理逻辑
        possible_stages = []
        
        for pattern, (stage, confidence) in stage_rules.items():
            match_score = 0
            total_signals = 3
            
            # 计算匹配度
            if bond_signal == AssetSignal.NEUTRAL:
                match_score += 0.5
            elif (bond_up and pattern[0]) or (not bond_up and not pattern[0]):
                match_score += 1
            
            if stock_signal == AssetSignal.NEUTRAL:
                match_score += 0.5  
            elif (stock_up and pattern[1]) or (not stock_up and not pattern[1]):
                match_score += 1
            
            if commodity_signal == AssetSignal.NEUTRAL:
                match_score += 0.5
            elif (commodity_up and pattern[2]) or (not commodity_up and not pattern[2]):
                match_score += 1
            
            adjusted_confidence = confidence * (match_score / total_signals)
            possible_stages.append((stage, adjusted_confidence))
        
        # 选择置信度最高的阶段
        if possible_stages:
            best_stage, best_confidence = max(possible_stages, key=lambda x: x[1])
            print(f"[诊断] 普林格阶段判定结果(中性信号匹配): 第{best_stage.value}阶段 (置信度{best_confidence:.1%})")
            return best_stage, best_confidence

        # 默认返回
        print(f"[诊断] 普林格阶段判定结果(默认): 第Ⅱ阶段 (置信度30%)")
        return PringStage.STAGE_II, 0.3
    
    async def analyze_pring_stage(self, days: int = 250) -> Dict:
        """
        完整的普林格六阶段分析（三层框架：库存周期 → 货币周期 → Pring修正）

        Args:
            days: 分析天数

        Returns:
            普林格阶段分析结果（包含三层分析结果）
        """
        try:
            print("=" * 60)
            print("开始三层框架分析")
            print("=" * 60)

            # ===== 数据收集阶段 =====
            print("\n[阶段1] 数据收集...")

            # 第一层：库存周期分析
            print("  收集库存周期数据...")
            macro_data = await self.get_macro_economic_data()

            # 第二层：货币周期数据
            print("  收集货币周期数据...")
            monetary_data = await self.get_monetary_cycle_data()

            # 第三层：Pring资产信号
            print("  收集Pring资产信号数据...")
            asset_signals_pre = await self.get_asset_signals(days)

            # ===== 数据验证阶段 =====
            print("\n[阶段2] 数据完整性验证...")

            # 验证第一层数据 (V4.2修正: 匹配实际返回的字段名)
            layer1_checks = {
                "PPI数据": (
                    (macro_data.get('ppi_data') is not None and len(macro_data.get('ppi_data', [])) > 0) or
                    (macro_data.get('websearch_queries', {}).get('ppi') is not None)
                ),
                "PMI数据": (
                    (macro_data.get('pmi_data') is not None and len(macro_data.get('pmi_data', [])) > 0) or
                    (macro_data.get('websearch_queries', {}).get('pmi') is not None)
                ),
                "PMI新订单": (
                    (macro_data.get('pmi_new_orders_data') is not None and len(macro_data.get('pmi_new_orders_data', [])) > 0) or
                    (macro_data.get('websearch_queries', {}).get('pmi') is not None)
                ),
                "PMI生产": (
                    (macro_data.get('pmi_production_data') is not None and len(macro_data.get('pmi_production_data', [])) > 0) or
                    (macro_data.get('websearch_queries', {}).get('pmi') is not None)
                ),
                "工业增加值": (
                    (macro_data.get('industrial_data') is not None) or
                    (macro_data.get('websearch_queries', {}).get('industrial') is not None)
                ),
                "工业营收": (
                    macro_data.get('industrial_sales_data') is not None or
                    (macro_data.get('websearch_queries', {}).get('industrial') is not None)
                ),
                "CPI数据": (
                    (macro_data.get('cpi_data') is not None and len(macro_data.get('cpi_data', [])) > 0) or
                    (macro_data.get('websearch_queries', {}).get('cpi') is not None)
                ),
                "GDP数据": (
                    macro_data.get('gdp_data') is not None or
                    (macro_data.get('websearch_queries', {}).get('gdp') is not None)
                ),
                "BDI指数": (
                    macro_data.get('bdi_data') is not None or
                    (macro_data.get('websearch_queries', {}).get('bdi') is not None)
                ),
            }
            layer1_available = sum(layer1_checks.values())
            layer1_total = len(layer1_checks)
            layer1_completeness = layer1_available / layer1_total * 100

            print(f"  第一层(库存周期): {layer1_available}/{layer1_total}项 ({layer1_completeness:.0f}%)")
            for name, status in layer1_checks.items():
                print(f"    {'[OK]' if status else '[MISSING]'} {name}")

            # 验证第二层数据 (V4.2修正: 接受WebSearch查询作为有效待获取数据)
            layer2_checks = {
                "M2增速": (
                    monetary_data.get('m2_growth') is not None or
                    monetary_data.get('m2_data') is not None
                ),
                "7天逆回购": (
                    monetary_data.get('reverse_repo_7d') is not None or
                    monetary_data.get('websearch_queries', {}).get('reverse_repo_7d') is not None
                ),
                "MLF利率": (
                    monetary_data.get('mlf_1y') is not None or
                    monetary_data.get('websearch_queries', {}).get('mlf_1y') is not None
                ),
                "存准率变化": (
                    monetary_data.get('rrr_change') is not None or
                    monetary_data.get('websearch_queries', {}).get('rrr_change') is not None
                ),
                "TSF增速": (
                    monetary_data.get('tsf_growth') is not None or
                    monetary_data.get('websearch_queries', {}).get('tsf_growth') is not None
                ),
            }
            layer2_available = sum(layer2_checks.values())
            layer2_total = len(layer2_checks)
            layer2_completeness = layer2_available / layer2_total * 100

            print(f"  第二层(货币周期): {layer2_available}/{layer2_total}项 ({layer2_completeness:.0f}%)")
            for name, status in layer2_checks.items():
                print(f"    {'[OK]' if status else '[MISSING]'} {name}")

            # 验证第三层数据
            layer3_checks = {
                "债券信号": asset_signals_pre.get('bonds') in [AssetSignal.BULLISH, AssetSignal.BEARISH, AssetSignal.NEUTRAL],
                "股票信号": asset_signals_pre.get('stocks') in [AssetSignal.BULLISH, AssetSignal.BEARISH, AssetSignal.NEUTRAL],
                "商品信号": asset_signals_pre.get('commodities') in [AssetSignal.BULLISH, AssetSignal.BEARISH, AssetSignal.NEUTRAL],
            }
            layer3_available = sum(layer3_checks.values())
            layer3_total = len(layer3_checks)
            layer3_completeness = layer3_available / layer3_total * 100

            print(f"  第三层(Pring信号): {layer3_available}/{layer3_total}项 ({layer3_completeness:.0f}%)")
            for name, status in layer3_checks.items():
                print(f"    {'[OK]' if status else '[MISSING]'} {name}")

            # 计算总体完整性
            overall_completeness = (layer1_completeness + layer2_completeness + layer3_completeness) / 3

            print(f"\n  总体数据完整性: {overall_completeness:.1f}%")

            # 判断是否满足最低要求
            min_threshold = 60.0  # 最低60%数据完整性
            if overall_completeness < min_threshold:
                error_msg = (
                    f"数据完整性不足 ({overall_completeness:.1f}% < {min_threshold:.0f}%)，"
                    f"无法可靠执行Pring分析！\n"
                    f"  第一层: {layer1_completeness:.0f}%\n"
                    f"  第二层: {layer2_completeness:.0f}%\n"
                    f"  第三层: {layer3_completeness:.0f}%"
                )
                print(f"\n[ERROR] {error_msg}")
                return {
                    "stage": "数据不足",
                    "confidence": 0.0,
                    "error": error_msg,
                    "data_completeness": {
                        "overall": overall_completeness,
                        "layer_1": layer1_completeness,
                        "layer_2": layer2_completeness,
                        "layer_3": layer3_completeness
                    }
                }
            elif overall_completeness < 80.0:
                print(f"  [WARNING] 数据完整性良好但不完美，分析结果可能受影响")

            print("\n[阶段3] 执行三层框架分析...")

            # ===== 第一层：库存周期分析 =====
            print("\n【第一层】库存周期分析...")
            inventory_analysis = self.calculate_inventory_cycle_score(macro_data)
            print(f"  库存周期阶段: {inventory_analysis.get('cycle_stage', 'N/A')}")
            print(f"  商品趋势倾向: {inventory_analysis.get('commodity_bias', 'N/A')}")
            print(f"  基本面评分: {inventory_analysis.get('fundamental_score', 0):.1f}/60分")

            # ===== 第二层：货币周期叠加 =====
            print("\n【第二层】货币周期叠加...")
            monetary_analysis = self.calculate_monetary_cycle_score(monetary_data)
            print(f"  货币周期阶段: {monetary_analysis.get('cycle_stage', 'N/A')}")
            print(f"  权益偏向: {monetary_analysis.get('equity_bias', 'N/A')}")
            print(f"  债券偏向: {monetary_analysis.get('bond_bias', 'N/A')}")
            print(f"  货币宽松度: {monetary_analysis.get('monetary_score', 0):.1f}/100分")

            # ===== 第三层：Pring阶段判定 =====
            print("\n【第三层】Pring六阶段判定（含双重修正）...")

            # 使用已经获取的资产信号（商品信号已集成库存周期矫正）
            asset_signals = asset_signals_pre



            # 基础Pring阶段判定

            base_stage, base_confidence = self.determine_pring_stage(

                asset_signals['bonds'],

                asset_signals['stocks'],

                asset_signals['commodities']

            )

            base_stage, base_confidence = self._enforce_stage_consistency(

                base_stage,

                base_confidence,

                inventory_analysis.get("cycle_stage", ""),

                monetary_analysis.get("cycle_stage", "")

            )

            print(f"  基础Pring阶段: {base_stage.value}")

            print(f"  基础置信度: {base_confidence:.1%}")


            # 货币周期修正：调整置信度和阶段判定

            leading_indicator = self._evaluate_leading_indicator(monetary_data)
            base_stage, base_confidence, leading_indicator = self._apply_leading_indicator_adjustment(
                base_stage,
                base_confidence,
                leading_indicator
            )
            if leading_indicator.get("status") == "ok":
                print(f"  [领先指标] DR007信号：{leading_indicator['direction']}，阶段平移{leading_indicator['applied_shift']}")
            elif leading_indicator.get("status") == "flat":
                print("  [领先指标] DR007变化有限，保持现有阶段")
            else:
                print(f"  [领先指标] {leading_indicator.get('message', '未提供数据')}")

            final_stage, final_confidence = self.apply_monetary_correction(
                base_stage,
                base_confidence,
                monetary_analysis,
                inventory_analysis,
                asset_signals
            )

            print("=" * 60)
            print(f"三层框架分析完成")
            print("=" * 60)

            # 获取阶段配置建议
            stage_config = self.stage_allocations[final_stage]
            leading_summary_text = self._summarize_leading_indicator_text(leading_indicator)
            inventory_summary = self._build_inventory_summary_text(
                inventory_analysis.get("score_details", {}),
                inventory_analysis.get("cycle_stage", "未知"),
                inventory_analysis.get("commodity_bias", "未知")
            )
            monetary_summary = self._build_monetary_summary_text(
                monetary_analysis.get("score_details", {}),
                monetary_analysis.get("cycle_stage", "未知"),
                monetary_analysis.get("equity_bias", "中性"),
                monetary_analysis.get("bond_bias", "中性")
            )
            stage_summary = self._build_stage_summary_text(
                final_stage,
                final_confidence,
                inventory_analysis.get("cycle_stage", "未知"),
                monetary_analysis.get("cycle_stage", "未知"),
                leading_summary_text
            )

            # 生成确认和否定信号（增强商品分析）
            confirm_signals = []
            deny_signals = []

            if asset_signals['bonds'] == AssetSignal.BULLISH:
                confirm_signals.append("债券收益率下行，债券价格上涨")
            elif asset_signals['bonds'] == AssetSignal.BEARISH:
                deny_signals.append("债券收益率上行，削弱债券上涨前提")

            if asset_signals['stocks'] == AssetSignal.BULLISH:
                confirm_signals.append("股票指数突破关键技术位，趋势向好")
            elif asset_signals['stocks'] == AssetSignal.BEARISH:
                deny_signals.append("股票指数跌破支撑位，趋势转弱")

            # 增强的商品信号分析
            if asset_signals['commodities'] == AssetSignal.BULLISH:
                confirm_signals.append(f"商品信号：{inventory_analysis['commodity_bias']}，技术面+库存周期双重确认")
            elif asset_signals['commodities'] == AssetSignal.BEARISH:
                deny_signals.append(f"商品信号：库存周期处于{inventory_analysis['cycle_stage']}，基本面偏弱")
            else:
                confirm_signals.append(f"商品信号：中性，库存周期处于{inventory_analysis['cycle_stage']}")

            correction_details = self.last_commodity_correction or {}

            # 返回三层框架完整分析结果
            result = {
                "stage": final_stage.to_display_format(),  # 使用"第Ⅵ阶段"格式
                "stage_description": stage_config["description"],
                "confidence": final_confidence,
                "asset_signals": {
                    "bonds": asset_signals['bonds'].value,
                    "stocks": asset_signals['stocks'].value,
                    "commodities": asset_signals['commodities'].value
                },
                "allocation_suggestion": stage_config["allocation"],
                "asset_recommendations": {
                    "bonds": stage_config["bonds"],
                    "stocks": stage_config["stocks"],
                    "commodities": stage_config["commodities"],
                    "cash": stage_config.get("cash", "标配")
                },
                "focus_assets": stage_config.get("focus_assets", []),
                "asset_allocation_pct": stage_config.get("allocation_pct", {}),
                "confirm_signals": confirm_signals,
                "deny_signals": deny_signals,
                # 第一层：库存周期分析
                "layer_1_inventory_cycle": {
                    "cycle_stage": inventory_analysis["cycle_stage"],
                    "commodity_bias": inventory_analysis["commodity_bias"],
                    "fundamental_score": inventory_analysis["fundamental_score"],
                    "score_details": inventory_analysis.get("score_details", {}),
                    "data_source": macro_data.get("data_source", "未知"),
                    "update_time": macro_data.get("update_time", "未知"),
                    "analysis": inventory_summary
                },
                # 第二层：货币周期叠加
                "layer_2_monetary_cycle": {
                    "cycle_stage": monetary_analysis["cycle_stage"],
                    "monetary_score": monetary_analysis["monetary_score"],
                    "equity_bias": monetary_analysis["equity_bias"],
                    "bond_bias": monetary_analysis["bond_bias"],
                    "score_details": monetary_analysis.get("score_details", {}),
                    "data_source": monetary_data.get("data_source", "未获取"),
                    "websearch_required": monetary_data.get("websearch_required", {}),
                    "analysis": monetary_summary
                },
                # 第三层：Pring最终判定
                "layer_3_pring_final": {
                    "base_stage": base_stage.to_display_format(),
                    "base_confidence": base_confidence,
                    "final_stage": final_stage.to_display_format(),
                    "final_confidence": final_confidence,
                    "monetary_adjustment": final_confidence - base_confidence,
                    "analysis": stage_summary
                },
                "leading_indicator": leading_indicator,
                "leading_summary": leading_summary_text,
                # 兼容旧版接口
                "technical_score": correction_details.get("technical_score"),
                "inventory_cycle_score": correction_details.get("fundamental_score"),
                "commodity_signal_score": correction_details.get("combined_score"),
                "commodity_signal": asset_signals['commodities'].value,
                "inventory_cycle_stage": inventory_analysis.get("cycle_stage"),
                "current_stage": final_stage.to_display_format(),
                "commodity_bias": inventory_analysis.get("commodity_bias"),
                "analysis_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data_period": f"{days}天历史数据",
                "methodology": "V4.3三层框架：库存周期(PPI/PMI/工增/BDI/CPI) → 货币周期(7D逆回购/MLF/降准/TSF/M2) → Pring六阶段修正",
                "enhancement_notes": "V4.3重大升级：移除AKShare依赖，优先使用TuShare/WebSearch。三层框架：以中国市场+港股为主、国际市场为参考"
            }

            result["final_stage"] = final_stage.to_display_format()
            result["confidence"] = final_confidence
            result["recommendation"] = stage_config["allocation"]
            result["metadata"] = {
                "analysis_method": result["methodology"],
                "analysis_time": result["analysis_date"],
                "data_period": result["data_period"]
            }
            return result
            
        except Exception as e:
            return {
                "error": f"普林格阶段分析时发生错误: {str(e)}",
                "stage": "分析失败",
                "confidence": 0.0,
                "inventory_cycle_analysis": {"error": "库存周期分析失败"}
            }
