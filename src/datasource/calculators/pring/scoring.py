"""Scoring helpers for Pring stage analysis."""

from typing import Any, Dict, Optional, Tuple


def _score_ppi_indicator(value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "PPI缺失，按中性处理"
    if value >= 0.5:
        return weight, "PPI转正，企业补库意愿增强"
    if value >= -1.0:
        return weight * 0.7, "PPI降幅收窄，价格端改善"
    return weight * 0.3, "PPI深度通缩，库存压力仍大"

def _score_cpi_indicator(value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "CPI缺失，按中性处理"
    if 0 <= value <= 3:
        return weight, "CPI温和运行，内需韧性可接受"
    if -0.5 <= value < 0:
        return weight * 0.6, "轻微通缩，需求仍偏弱"
    if 3 < value <= 5:
        return weight * 0.6, "温和通胀，库存去化继续"
    return weight * 0.3, "高通胀或深度通缩波动，压制补库"

def _score_pmi_indicator(value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "PMI缺失，按中性处理"
    if value >= 50.5:
        return weight, "PMI站稳荣枯线上方，补库动能充足"
    if value >= 50.0:
        return weight * 0.85, "PMI略高于荣枯线，补库初显"
    if value >= 48.0:
        return weight * 0.55, "PMI仍在收缩区，景气承压"
    return weight * 0.25, "PMI深度低于荣枯线，库存主动去化"

def _score_industrial_value_indicator(value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "工业增加值缺失，按中性处理"
    if value >= 5.5:
        return weight, "工业增加值维持高位增长"
    if value >= 4.5:
        return weight * 0.8, "工业增速平稳，库存逐步修复"
    if value >= 3.5:
        return weight * 0.6, "工业增速放缓，库存回补偏谨慎"
    return weight * 0.3, "工业增速疲弱，库存去化压力大"

def _score_industrial_sales_indicator(value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "工业营收缺失，按中性处理"
    if value >= 5.0:
        return weight, "工业企业营收高增，终端需求改善"
    if value >= 0.0:
        return weight * 0.6, "营收小幅增长，需求恢复仍不均衡"
    return weight * 0.3, "营收同比为负，需求拖累库存"

def _score_gdp_indicator(value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "GDP缺失，按中性处理"
    if value >= 5.5:
        return weight, "GDP保持高景气，补库动力充足"
    if value >= 5.0:
        return weight * 0.8, "GDP略高于潜在增速，库存温和回补"
    if value >= 4.0:
        return weight * 0.6, "GDP放缓，需要政策托底"
    return weight * 0.3, "GDP增速偏弱，库存去化占主导"

def _score_bdi_indicator(value: Optional[float], weight: float, entry: Optional[Dict[str, Any]]) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "BDI缺失，按中性处理"
    if value >= 2000:
        return weight, "BDI高位运行，全球补库交易旺盛"
    if value >= 1500:
        return weight * 0.7, "BDI维持景气区间"
    if value >= 1000:
        return weight * 0.5, "BDI中性震荡"
    return weight * 0.3, "BDI偏弱，需求侧仍谨慎"

def _score_rrr_change(change: Optional[float], weight: float) -> Tuple[float, str]:
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

def _score_policy_rate_change(change: Optional[float], weight: float) -> Tuple[float, str]:
    if change is None:
        return weight * 0.5, "缺少逆回购利率变动，按中性处理"
    if change <= -0.15:
        return weight, "逆回购利率累计下调≥15bp，政策明显宽松"
    if change <= -0.05:
        return weight * 0.75, "逆回购利率小幅下调"
    if change < 0.02:
        return weight * 0.45, "利率基本持平"
    return weight * 0.25, "逆回购利率上调，政策趋紧"

def _score_dr007_change(change: Optional[float], weight: float) -> Tuple[float, str]:
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

def _score_tsf_growth(value: Optional[float], weight: float) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "缺少TSF增速，按中性处理"
    if value >= 10:
        return weight, "社融增速≥10%，融资需求旺盛"
    if value >= 8:
        return weight * 0.8, "社融增速8-10%，宽信用持续"
    if value >= 6:
        return weight * 0.5, "社融增速6-8%，中性"
    return weight * 0.2, "社融增速低于6%，信用扩张偏弱"

def _score_m2_growth(value: Optional[float], weight: float) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "缺少M2增速，按中性处理"
    if value >= 10:
        return weight, "M2两位数增长，流动性充沛"
    if value >= 8:
        return weight * 0.8, "M2增速8-10%，温和宽松"
    if value >= 6:
        return weight * 0.55, "M2增速6-8%，中性"
    return weight * 0.3, "M2增速<6%，货币供给偏紧"

def _score_m1_growth(value: Optional[float], weight: float) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "缺少M1增速，按中性处理"
    if value >= 8:
        return weight, "M1快速增长，企业活期需求上升"
    if value >= 5:
        return weight * 0.75, "M1增速温和回升"
    if value >= 3:
        return weight * 0.5, "M1增速中性"
    return weight * 0.25, "M1低增或为负，实体需求偏弱"

def _score_m1_m2_spread(value: Optional[float], weight: float) -> Tuple[float, str]:
    if value is None:
        return weight * 0.5, "缺少剪刀差数据，按中性处理"
    if value >= 1.0:
        return weight, "M1-M2剪刀差>1pct，流动性向实体回流"
    if value >= 0.0:
        return weight * 0.7, "剪刀差大致为正"
    if value >= -1.0:
        return weight * 0.45, "剪刀差略负，需求恢复有限"
    return weight * 0.2, "剪刀差深度为负，货币传导不畅"
