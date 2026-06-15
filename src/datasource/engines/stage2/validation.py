"""Validation helpers for Stage2 extraction results."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from datasource.engines.stage2.common import _RANGE_RULES, _safe_number
from datasource.engines.stage2.snippet_filters import _is_stale
from datasource.utils.source_trust import units_compatible


_FUND_FLOW_BOUNDS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "northbound": {
        "recent_5d": (-500.0, 500.0),
        "total_120d": (-8000.0, 8000.0),
    },
    "southbound": {
        "recent_5d": (-500.0, 500.0),
        "total_120d": (-8000.0, 8000.0),
    },
    "etf": {
        "recent_5d": (-8000.0, 8000.0),
        "total_120d": (-30000.0, 30000.0),
    },
    "margin": {
        "recent_5d": (-8000.0, 8000.0),
        "total_120d": (-50000.0, 50000.0),
    },
}


def _detect_fund_flow_suspicious_reason(
    key: str,
    recent: Optional[float],
    total: Optional[float],
) -> Optional[str]:
    if recent is None or total is None:
        return None
    if key in {"northbound", "southbound"} and abs(recent - total) < 1e-9:
        if abs(recent - 100.0) < 1e-9:
            return "疑似占位值(100/100)"
        if abs(recent) <= 150.0:
            return "近5日与120日完全相等且偏小"

    bounds = _FUND_FLOW_BOUNDS.get(key, {})
    recent_bound = bounds.get("recent_5d")
    if recent_bound and not (recent_bound[0] <= recent <= recent_bound[1]):
        return f"recent_5d超出经验区间({recent_bound[0]}~{recent_bound[1]})"
    total_bound = bounds.get("total_120d")
    if total_bound and not (total_bound[0] <= total <= total_bound[1]):
        return f"total_120d超出经验区间({total_bound[0]}~{total_bound[1]})"
    return None


def _flag_fund_flow_anomalies(market_payload: Dict[str, Any]) -> List[str]:
    """标记资金流向的零值/空值/可疑占位值"""
    flagged: List[str] = []
    fund_flow = market_payload.get("fund_flow", {})
    for key, item in fund_flow.items():
        if not isinstance(item, dict):
            continue
        recent = _safe_number(item.get("recent_5d"))
        total = _safe_number(item.get("total_120d"))
        suspicious_reason = _detect_fund_flow_suspicious_reason(key, recent, total)  # noqa: E501
        if (recent is None or abs(recent) < 1e-9) or (total is None or abs(total) < 1e-9) or suspicious_reason:  # noqa: E501
            item["source"] = "异常零值-需核查"
            note = (item.get("note") or "").strip()
            anomaly_note = "异常零值-需核查"
            if suspicious_reason:
                anomaly_note = f"{anomaly_note} {suspicious_reason}"
            if anomaly_note not in note:
                note = (note + f" {anomaly_note}").strip()
            item["note"] = note
            item["manual_required"] = True
            flagged.append(key)
        else:
            # 兼容历史旧标注，统一归一到当前 Tavily 口径
            source_text = str(item.get("source") or "").lower()
            if "mcp" in source_text:
                item["source"] = "tavily+deepseek"
                note = (item.get("note") or "").strip()
                compat_note = "legacy_source_normalized:mcp->tavily"
                if compat_note not in note:
                    item["note"] = (note + f" {compat_note}").strip()
    return flagged


def _validate_fund_flow_extraction(
    extraction: Dict[str, Any], indicator_key: Optional[str] = None
) -> (Optional[float], bool, str):
    """确保资金流数值有“亿”单位，并基于关键词确定正负；返回 (value, manual_required, note_append)"""
    val = extraction.get("value")
    note_append = ""
    manual = False
    if val is None:
        return None, True, "no_value"
    try:
        val = float(val)
    except Exception:
        return None, True, "parse_error"
    # 单位校验
    unit = extraction.get("unit") or ""
    unit_lower = str(unit).lower()
    if "亿" not in unit and "bn" not in unit_lower and "billion" not in unit_lower:  # noqa: E501
        manual = True
        note_append = (note_append + " 单位缺失(需含亿)").strip()
    # 方向校验：根据 note / raw snippet 关键词推断
    text_blob = f"{extraction.get('note') or ''} {extraction.get('trend') or ''}".lower()  # noqa: E501
    direction_unknown = True
    if "流出" in text_blob or "net outflow" in text_blob:
        if val > 0:
            val = -val
        direction_unknown = False
    elif "流入" in text_blob or "net inflow" in text_blob or "买入" in text_blob:
        if val < 0:
            val = abs(val)
        direction_unknown = False
    elif "卖出" in text_blob:
        if val > 0:
            val = -val
        direction_unknown = False

    if abs(val) < 1e-9:
        manual = True
        note_append = (note_append + " 值为0需复核").strip()
    if direction_unknown:
        manual = True
        note_append = (note_append + " 未能识别流入/流出方向").strip()
    key = str(indicator_key or "").lower()
    if key in {"northbound", "southbound"}:
        if abs(val - 100.0) < 1e-9:
            manual = True
            note_append = (note_append + " 疑似占位值(100)").strip()
    bounds = _FUND_FLOW_BOUNDS.get(key)
    if bounds and "recent_5d" in bounds:
        low, high = bounds["recent_5d"]
        if not (low <= val <= high):
            manual = True
            note_append = (note_append + f" 超出经验区间({low}~{high})").strip()

    return val, manual, note_append


def _validate_general_extraction(
    extraction: Dict[str, Any], task: Dict[str, Any], snippets: Optional[List[Dict[str, Any]]] = None  # noqa: E501
) -> (Optional[float], bool, str):
    """
    对宏观/利率/商品等结果做基本校验：
    - unit_hint 存在但 extraction.unit 缺失或不包含 -> manual_required
    - preferred_domains 存在且 source_url 域名不在其中 -> manual_required
    - issuer_hint 提供但片段/抽取结果不包含发布机构 -> manual_required
    """
    val = extraction.get("value")
    unit_hint = task.get("unit")
    domains = task.get("preferred_domains") or []
    issuer_hint = task.get("issuer")
    issuer_aliases = task.get("issuer_aliases") or []
    indicator_key = task.get("indicator_key")
    indicator_key_l = str(indicator_key or "").lower()
    manual = False
    note_append = ""
    note_flag = extraction.get("note") or ""
    snippets_text = " ".join(
        [
            str(s.get("content", "")) or str(s.get("snippet", "")) or ""
            for s in (snippets or [])
        ]
    ).lower()

    if val is None:
        manual = True
        note_append = (note_append + " no_value").strip()

    # unit 校验使用与官方来源信任一致的 canonical unit 规则。
    if unit_hint:
        unit_val = extraction.get("unit") or ""
        if not units_compatible(unit_hint, unit_val):
            manual = True
            note_append = (note_append + f" 单位不匹配(需含{unit_hint})").strip()

    # 域名校验
    src = extraction.get("source_url")
    src_netloc = ""
    if src:
        try:
            src_netloc = urlparse(src).netloc
        except Exception:
            src_netloc = ""
    if domains and src:
        try:
            netloc = src_netloc or urlparse(src).netloc
            if not any(netloc.endswith(d) for d in domains):
                manual = True
                note_append = (note_append + " 域名不在白名单").strip()
            # regex_only 时 URL 过于泛（如首页）时标记人工
            strict_regex_keys = {"USDCNY", "USDCNH", "DXY", "bdi"}
            if (
                indicator_key in strict_regex_keys
                and isinstance(note_flag, str)
                and note_flag.startswith("regex")
                and urlparse(src).path in {"", "/"}
            ):
                manual = True
                note_append = (note_append + " regex_only来源过泛").strip()
        except Exception:
            manual = True
            note_append = (note_append + " source_url解析失败").strip()

    # 发布机构校验：若提供 issuer_hint，需要在抽取或片段中出现
    if issuer_hint:
        issuer_relax_domains = {
            "rrr": ["tradingeconomics.com", "ceicdata.com", "chinamoney.com.cn"],  # noqa: E501
            "mlf": ["tradingeconomics.com", "chinamoney.com.cn"],
            "reverse_repo": ["tradingeconomics.com", "chinamoney.com.cn", "cls.cn"],  # noqa: E501
            "bcom": ["tradingeconomics.com", "investing.com", "bloomberg.com"],
            "cn10y": ["tradingeconomics.com", "ceicdata.com", "macromicro.me", "investing.com"],  # noqa: E501
            "cn10y_cdb": ["chinamoney.com.cn", "cfets.com.cn", "eastmoney.com", "tradingeconomics.com", "ceicdata.com"],  # noqa: E501
            "bdi": ["balticexchange.com", "tradingeconomics.com", "investing.com"],  # noqa: E501
        }
        issuer_relaxed = False
        if indicator_key_l in issuer_relax_domains and src_netloc:
            issuer_relaxed = any(
                src_netloc.endswith(d) for d in issuer_relax_domains[indicator_key_l]  # noqa: E501
            )
        issuer_match_flag = extraction.get("issuer_match")
        alias_hit = any(alias.lower() in snippets_text for alias in issuer_aliases)  # noqa: E501
        if (
            not issuer_relaxed
            and not issuer_match_flag
            and issuer_hint.lower() not in snippets_text
            and not alias_hit
        ):
            # 若已有有效数值但缺发行人，则仅提示不强制人工；无值则仍需人工
            if val is None:
                manual = True
            note_append = (note_append + f" 缺少发布机构({issuer_hint})").strip()
        elif issuer_relaxed:
            note_append = (note_append + " 发布机构校验放宽").strip()
        # regex_only/regex_fallback 情况下，对关键指标要求发布机构命中
        strict_issuer_keys = {
            "usdcny",
            "usdcnh",
            "dxy",
            "bdi",
            "rrr",
            "mlf",
            "reverse_repo",
        }
        if (
            indicator_key_l in strict_issuer_keys
            and isinstance(note_flag, str)
            and note_flag.startswith("regex")
            and not issuer_match_flag
            and issuer_hint.lower() not in snippets_text
            and not alias_hit
            and not issuer_relaxed
        ):
            if val is None:
                manual = True
            note_append = (note_append + f" regex_only缺少发布机构({issuer_hint})").strip()  # noqa: E501

    # regex_only 时要求命中指标关键词，避免抓取无关数字
    if isinstance(note_flag, str) and note_flag.startswith("regex") and indicator_key:  # noqa: E501
        keyword_rules = {
            "USDCNY": [
                "usdcny",
                "usd/cny",
                "usd cny",
                "us dollar",
                "chinese yuan",
                "cny",
                "renminbi",
                "美元",
                "人民币",
                "在岸",
                "中间价",
            ],
            "USDCNH": [
                "usdcnh",
                "usd/cnh",
                "usd cnh",
                "offshore",
                "cnh",
                "renminbi",
                "离岸人民币",
            ],
            "DXY": ["dxy", "美元指数", "dollar index", "us dollar index", "ice dollar index"],  # noqa: E501
            "bdi": ["bdi", "波罗的海", "baltic"],
            "industrial": ["工业增加值", "规模以上工业增加值", "industrial output"],  # noqa: E501
            "industrial_sales": ["工业企业", "营业收入", "营收", "industrial enterprise"],  # noqa: E501
            "rrr": ["存款准备金率", "rrr", "降准", "reserve requirement"],
            "mlf": ["mlf", "中期借贷便利", "medium-term lending facility"],
            "reverse_repo": ["逆回购", "repo", "reverse repo", "7-day"],
            "US10Y": ["10年", "10-year", "us10y", "treasury"],
            "CN10Y": ["10年", "10-year", "10 year", "10y", "国债", "government bond", "china 10y"],  # noqa: E501
            "CN10Y_CDB": ["国开", "开发债", "政策性金融债", "中债估值", "cdb"],
        }
        keywords = keyword_rules.get(indicator_key)
        if keywords and not any(k.lower() in snippets_text for k in keywords):
            manual = True
            note_append = (note_append + " regex_only缺少指标关键词").strip()

    # 时效性校验：若所有可解析日期均超过设定阈值，则标记人工复核
    max_age = task.get("max_age_days")
    if max_age and _is_stale(snippets, max_age):
        manual = True
        note_append = (note_append + f" 数据超过{max_age}天需更新").strip()

    # 合理区间校验：对易被新闻数字干扰的指标做基本范围限制
    if indicator_key in _RANGE_RULES:
        numeric_val = _safe_number(val)
        if numeric_val is not None:
            low, high = _RANGE_RULES[indicator_key]
            if numeric_val < low or numeric_val > high:
                manual = True
                note_append = (note_append + f" 数值超出合理区间({low}-{high})").strip()  # noqa: E501
        elif val is not None:
            manual = True
            note_append = (note_append + " 数值不可解析").strip()

    # 工业增加值口径保护：仅累计同比时不作为 current_value 使用
    if indicator_key == "industrial" and extraction.get("value_type") == "yoy_ytd":  # noqa: E501
        manual = True
        note_append = (note_append + " 仅累计同比需补当月同比").strip()

    return val, manual, note_append
