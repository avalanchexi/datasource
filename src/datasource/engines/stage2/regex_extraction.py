"""Regex fallback and structured extraction helpers for Stage2."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _regex_fallback(snippets: List[Dict[str, Any]], indicator: str) -> Optional[float]:  # noqa: E501
    """
    针对常见官网文本的兜底数值提取。
    适用：industrial/industrial_sales/bdi/mlf/rrr/reverse_repo 等。
    """
    if not snippets:
        return None
    text = " ".join(
        str(s.get("content") or s.get("snippet") or "") for s in snippets
    )
    ind = indicator.lower()
    patterns: List[str] = []
    if ind == "industrial":
        patterns = [
            r"(?:规模以上)?工业增加值[^\\d]{0,20}(?:同比|增长)[^\\d]{0,10}([-+]?\\d+(?:\\.\\d+)?)\\s*%",  # noqa: E501
        ]
    elif ind == "industrial_sales":
        patterns = [
            r"(?:规模以上)?工业企业[^\\d]{0,20}(?:营业收入|营收)[^\\d]{0,20}(?:同比|增长)[^\\d]{0,10}([-+]?\\d+(?:\\.\\d+)?)\\s*%",  # noqa: E501
        ]
    elif ind == "mlf":
        patterns = [r"(?:mlf|中期借贷便利)[^\\d]*([-+]?\\d+(?:\\.\\d+)?)\\s*[%％]"]
    elif ind == "reverse_repo":
        patterns = [r"(?:逆回购|repo)[^\\d]*([-+]?\\d+(?:\\.\\d+)?)\\s*%"]
    elif ind == "rrr":
        patterns = [r"(?:存款准备金率|rrr|降准)[^\\d]*([-+]?\\d+(?:\\.\\d+)?)\\s*%"]
    elif ind == "bdi":
        patterns = [r"(?:BDI|波罗的海)[^\\d]*([-+]?\\d{3,5}(?:\\.\\d+)?)"]
    elif ind == "usdcny":
        patterns = [
            r"(?:USDCNY|USD/CNY|USD CNY|美元/人民币|美元人民币)[^\\d]*([0-9]+\\.\\d{2,6})",  # noqa: E501
            r"1(?:\\.0+)?\\s*USD\\s*=\\s*([0-9]+\\.\\d{2,6})\\s*CNY",
        ]
    elif ind == "usdcnh":
        patterns = [
            r"(?:USDCNH|USD/CNH|USD CNH|离岸人民币)[^\\d]*([0-9]+\\.\\d{2,6})",
            r"1(?:\\.0+)?\\s*USD\\s*=\\s*([0-9]+\\.\\d{2,6})\\s*CNH",
        ]
    elif ind == "dxy":
        patterns = [
            r"(?:DXY|美元指数|Dollar Index|US Dollar Index)[^\\d]*([0-9]{2,3}(?:\\.\\d+)?)",  # noqa: E501
            r"([0-9]{2,3}(?:\\.\\d+)?)\\s*(?:DXY|美元指数|Dollar Index)",
        ]
    elif ind == "us10y":
        patterns = [r"(?:US10Y|美国10年|10年期国债|10-year)[^\\d]*([0-9]+\\.\\d{2,3})\\s*%?"]  # noqa: E501
    elif ind == "cn10y":
        patterns = [
            r"(?:中国10年|10年期国债|China\\s*10\\s*Y|10[- ]?year|10y)[^\\d]*([0-9]+\\.\\d{2,3})\\s*%?",  # noqa: E501
            r"([0-9]+\\.\\d{2,3})\\s*%?[^\\d]*(?:China\\s*10\\s*Y|10[- ]?year|10y)",  # noqa: E501
        ]
    elif ind == "cn10y_cdb":
        patterns = [r"(?:国开|国开债|开发债)[^\\d]*([0-9]+\\.\\d{2,3})\\s*%?"]
    else:
        return None

    for pat in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                continue
    return None


def _collect_snippet_text(snippets: List[Dict[str, Any]]) -> str:
    return " ".join(
        str(s.get("content") or s.get("snippet") or "") for s in snippets
    )


def _find_number_by_patterns(
    text: str,
    patterns: List[str],
    low: Optional[float] = None,
    high: Optional[float] = None,
    min_decimals: Optional[int] = None,
    require_nonzero_decimal: bool = False,
) -> Optional[float]:
    for pat in patterns:
        for m in re.finditer(pat, text, flags=re.IGNORECASE | re.DOTALL):
            num = m.group(1)
            if "." in num:
                decimals = num.split(".", 1)[1]
                if min_decimals is not None and len(decimals) < min_decimals:
                    continue
                if require_nonzero_decimal and set(decimals) <= {"0"}:
                    continue
            elif min_decimals is not None:
                continue
            try:
                val = float(num)
            except Exception:
                continue
            if low is not None and val < low:
                continue
            if high is not None and val > high:
                continue
            return val
    return None


def _extract_structured_value(snippets: List[Dict[str, Any]], indicator: str) -> Optional[float]:  # noqa: E501
    if not snippets:
        return None
    text = _collect_snippet_text(snippets)
    ind = indicator.lower()
    if ind == "usdcny":
        patterns = [
            r"(?:USDCNY|USD/CNY|USD CNY|美元/人民币|美元人民币|在岸人民币)[^\\d]{0,12}([0-9]+\\.\\d{2,6})",  # noqa: E501
            r"1(?:\\.0+)?\\s*USD\\s*=\\s*([0-9]+\\.\\d{2,6})\\s*CNY",
        ]
        return _find_number_by_patterns(text, patterns, 5.5, 9.5, min_decimals=2, require_nonzero_decimal=True)  # noqa: E501
    if ind == "usdcnh":
        patterns = [
            r"(?:USDCNH|USD/CNH|USD CNH|离岸人民币|offshore)[^\\d]{0,12}([0-9]+\\.\\d{2,6})",  # noqa: E501
            r"1(?:\\.0+)?\\s*USD\\s*=\\s*([0-9]+\\.\\d{2,6})\\s*CNH",
        ]
        return _find_number_by_patterns(text, patterns, 5.5, 10.0, min_decimals=2, require_nonzero_decimal=True)  # noqa: E501
    if ind == "dxy":
        patterns = [
            r"(?:DXY|美元指数|Dollar Index|US Dollar Index)[^\\d]{0,12}([0-9]{2,3}\\.\\d{1,3})",  # noqa: E501
            r"([0-9]{2,3}\\.\\d{1,3})[^\\d]{0,12}(?:DXY|美元指数|Dollar Index|US Dollar Index)",  # noqa: E501
        ]
        return _find_number_by_patterns(text, patterns, 70.0, 140.0, min_decimals=1)  # noqa: E501
    if ind == "cn10y":
        patterns = [
            r"(?:China\\s*10\\s*Y|10[- ]?year|10y|10年|国债收益率)[^\\d]{0,12}([0-9]+\\.\\d{2,3})",  # noqa: E501
            r"([0-9]+\\.\\d{2,3})[^\\d]{0,12}(?:China\\s*10\\s*Y|10[- ]?year|10y|10年)",  # noqa: E501
        ]
        return _find_number_by_patterns(text, patterns, 0.0, 10.0, min_decimals=2)  # noqa: E501
    if ind == "rrr":
        patterns = [
            r"(?:存款准备金率|RRR|reserve requirement)[^\\d]{0,12}([0-9]+\\.\\d+)\\s*%?",  # noqa: E501
        ]
        return _find_number_by_patterns(text, patterns, 5.0, 20.0, min_decimals=1)  # noqa: E501
    if ind == "mlf":
        patterns = [
            r"(?:MLF|中期借贷便利|medium-term lending facility)[^\\d]{0,12}([0-9]+\\.\\d+)\\s*%?",  # noqa: E501
        ]
        return _find_number_by_patterns(text, patterns, 1.5, 5.0, min_decimals=1)  # noqa: E501
    if ind == "reverse_repo":
        patterns = [
            r"(?:逆回购|reverse repo|repo)[^\\d]{0,12}([0-9]+\\.\\d+)\\s*%?",
        ]
        return _find_number_by_patterns(text, patterns, 1.0, 5.0, min_decimals=1)  # noqa: E501
    return None


def _extract_flow_value(snippets: List[Dict[str, Any]], indicator: str) -> (Optional[float], Optional[str]):  # noqa: E501
    if not snippets:
        return None, None
    text = _collect_snippet_text(snippets)
    flow_patterns = [
        r"(?:北向资金|northbound|南向资金|southbound)[^\\d]{0,80}(?:净流入|净流出|净买入|net inflow|net outflow|net buy)[^\\d+\\-]{0,12}([+-]?\\d+(?:\\.\\d+)?)\\s*(亿元|亿港元|billion|bn)",  # noqa: E501
        r"(?:net inflow|net outflow|净流入|净流出|净买入)[^\\d+\\-]{0,12}([+-]?\\d+(?:\\.\\d+)?)\\s*(亿元|亿港元|billion|bn)",  # noqa: E501
    ]
    for pat in flow_patterns:
        m = re.search(pat, text, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        try:
            val = float(m.group(1))
        except Exception:
            continue
        seg = m.group(0).lower()
        direction = None
        if any(tok in seg for tok in ["净流出", "net outflow", "outflow", "卖出"]):
            direction = "outflow"
        elif any(tok in seg for tok in ["净流入", "net inflow", "net buy", "买入", "流入"]):  # noqa: E501
            direction = "inflow"
        if direction == "outflow" and val > 0:
            val = -abs(val)
        if direction == "inflow" and val < 0:
            val = abs(val)
        return val, direction
    unit_matches = re.findall(r"([+-]?\\d+(?:\\.\\d+)?)\\s*(亿元|亿港元|billion|bn)", text, flags=re.IGNORECASE)  # noqa: E501
    if unit_matches:
        try:
            vals = [float(v[0]) for v in unit_matches]
        except Exception:
            vals = []
        if vals:
            val = max(vals, key=lambda x: abs(x))
            return val, None
    return None, None


def _refine_extraction_value(
    extraction: Dict[str, Any], task: Dict[str, Any], snippets: Optional[List[Dict[str, Any]]]  # noqa: E501
) -> None:
    if not snippets:
        return
    indicator = (task.get("indicator_key") or "").lower()
    note = extraction.get("note") or ""
    confidence = extraction.get("confidence", 0.0) or 0.0
    if not (isinstance(note, str) and note.startswith("regex")) and confidence >= 0.6:  # noqa: E501
        return
    if indicator in {"northbound", "southbound"}:
        flow_val, direction = _extract_flow_value(snippets, indicator)
        if flow_val is not None:
            extraction["value"] = flow_val
            if direction:
                dir_cn = "流出" if direction == "outflow" else "流入"
                extraction["note"] = ((extraction.get("note") or "") + f" structured_dir:{direction} {dir_cn}").strip()  # noqa: E501
            else:
                extraction["note"] = ((extraction.get("note") or "") + " structured_value").strip()  # noqa: E501
        return
    refined = _extract_structured_value(snippets, indicator)
    if refined is not None:
        extraction["value"] = refined
        extraction["note"] = ((extraction.get("note") or "") + " structured_refine").strip()  # noqa: E501


def _infer_rrr_type(text: str) -> Optional[str]:
    if not text:
        return None
    if "加权" in text or "weighted" in text.lower():
        return "weighted"
    if "法定" in text or "statutory" in text.lower():
        return "statutory"
    return None
