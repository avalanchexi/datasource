"""Stage allocation templates for Pring stage analysis."""

from typing import Any, Dict


def build_stage_allocations(PringStage: Any) -> Dict[Any, Dict[str, Any]]:
    """构建普林格阶段的资产配置模板"""
    allocations = {
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

    expected_stages = {
        PringStage.STAGE_I,
        PringStage.STAGE_II,
        PringStage.STAGE_III,
        PringStage.STAGE_IV,
        PringStage.STAGE_V,
        PringStage.STAGE_VI,
    }
    assert set(allocations) == expected_stages
    return allocations
